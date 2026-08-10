#!/usr/bin/env python3
"""Verify that a wheel contains the exact current dashboard static tree."""

from __future__ import annotations

import argparse
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


WHEEL_STATIC_PREFIX = "weekly_cs_report/static/"
OBSOLETE_LANGFUSE_SESSION_MARKERS = (
    b"/sessions/",
    "Mở session ticket".encode(),
)
FIXED_LANGFUSE_90_DAY_RANGE_MARKER = b"dateRange=90d"
SPA_INDEX = "spa/index.html"
SPA_ENTRYPOINT_PATTERNS = (
    (
        "hashed JavaScript",
        re.compile(r"^spa/assets/index-[A-Za-z0-9_-]{6,}\.js$"),
    ),
    (
        "hashed stylesheet",
        re.compile(r"^spa/assets/index-[A-Za-z0-9_-]{6,}\.css$"),
    ),
)
NAVIGATION_TEXT_SUFFIXES = frozenset(
    {".css", ".html", ".js", ".json", ".mjs", ".txt"}
)


class WheelAssetValidationError(ValueError):
    """Raised when a wheel cannot prove static-asset parity with its source."""


class _SpaIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.script_sources: list[str | None] = []
        self.stylesheet_hrefs: list[str | None] = []
        self.forbidden_inline: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes: dict[str, list[str | None]] = {}
        for name, value in attrs:
            attributes.setdefault(name, []).append(value)

        if tag == "style":
            self.forbidden_inline.append("<style>")
        for name in attributes:
            if name == "style" or name.startswith("on"):
                self.forbidden_inline.append(f"<{tag} {name}>")

        if tag == "script":
            sources = attributes.get("src", [])
            self.script_sources.append(
                sources[0] if len(sources) == 1 else None
            )
            return

        if tag != "link":
            return
        relations = attributes.get("rel", [])
        relation_tokens = {
            token.lower()
            for relation in relations
            if relation is not None
            for token in relation.split()
        }
        if "stylesheet" not in relation_tokens:
            return
        hrefs = attributes.get("href", [])
        self.stylesheet_hrefs.append(hrefs[0] if len(hrefs) == 1 else None)


def _is_source_map(name: str) -> bool:
    return name.lower().endswith(".map")


def _is_navigation_text_asset(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in NAVIGATION_TEXT_SUFFIXES


def _source_assets(source_static: Path) -> dict[str, bytes]:
    if not source_static.is_dir():
        raise WheelAssetValidationError(
            f"source static directory does not exist: {source_static}"
        )

    symlinks = sorted(
        path.relative_to(source_static).as_posix()
        for path in source_static.rglob("*")
        if path.is_symlink()
    )
    if symlinks:
        raise WheelAssetValidationError(
            "source static tree contains symlinks: " + ", ".join(symlinks)
        )

    assets = {
        path.relative_to(source_static).as_posix(): path.read_bytes()
        for path in sorted(source_static.rglob("*"))
        if path.is_file()
    }
    if not assets:
        raise WheelAssetValidationError("source static directory is empty")

    source_maps = sorted(name for name in assets if _is_source_map(name))
    if source_maps:
        raise WheelAssetValidationError(
            "source map is forbidden in the source static tree: "
            + ", ".join(source_maps)
        )
    return assets


def _validate_static_archive_name(name: str) -> str:
    relative = name.removeprefix(WHEEL_STATIC_PREFIX)
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise WheelAssetValidationError(f"invalid wheel static entry: {name}")
    return relative


def _wheel_assets(wheel: Path) -> dict[str, bytes]:
    if not wheel.is_file():
        raise WheelAssetValidationError(f"wheel does not exist: {wheel}")

    try:
        with zipfile.ZipFile(wheel) as archive:
            infos = archive.infolist()
            source_maps = sorted(
                info.filename
                for info in infos
                if not info.is_dir() and _is_source_map(info.filename)
            )
            if source_maps:
                raise WheelAssetValidationError(
                    "source map is forbidden in the wheel: "
                    + ", ".join(source_maps)
                )

            static_infos = [
                info
                for info in infos
                if not info.is_dir()
                and info.filename.startswith(WHEEL_STATIC_PREFIX)
            ]
            names = [info.filename for info in static_infos]
            duplicates = sorted(
                name for name, count in Counter(names).items() if count > 1
            )
            if duplicates:
                raise WheelAssetValidationError(
                    "duplicate wheel static entries: " + ", ".join(duplicates)
                )

            return {
                _validate_static_archive_name(info.filename): archive.read(info)
                for info in static_infos
            }
    except zipfile.BadZipFile as exc:
        raise WheelAssetValidationError(f"invalid wheel archive: {wheel}") from exc


def _reject_obsolete_langfuse_session_navigation(
    assets: dict[str, bytes],
    *,
    location: str,
) -> None:
    stale_assets = sorted(
        name
        for name, content in assets.items()
        if _is_navigation_text_asset(name)
        and any(
            marker in content
            for marker in OBSOLETE_LANGFUSE_SESSION_MARKERS
        )
    )
    if stale_assets:
        raise WheelAssetValidationError(
            f"obsolete Langfuse Session navigation in {location}: "
            + ", ".join(stale_assets)
        )


def _reject_fixed_langfuse_date_range(
    assets: dict[str, bytes],
    *,
    location: str,
) -> None:
    stale_assets = sorted(
        name
        for name, content in assets.items()
        if _is_navigation_text_asset(name)
        and FIXED_LANGFUSE_90_DAY_RANGE_MARKER in content
    )
    if stale_assets:
        raise WheelAssetValidationError(
            f"fixed Langfuse 90-day navigation range in {location}: "
            + ", ".join(stale_assets)
        )


def validate_source_spa(source_static: Path | str) -> tuple[str, ...]:
    """Validate that source static contains a usable Vite production build."""

    assets = _source_assets(Path(source_static))
    index = assets.get(SPA_INDEX)
    if index is None:
        raise WheelAssetValidationError(
            "SPA index is missing; run `npm run build` before building a wheel"
        )

    entrypoints = []
    for label, pattern in SPA_ENTRYPOINT_PATTERNS:
        candidates = sorted(name for name in assets if pattern.fullmatch(name))
        if len(candidates) != 1:
            raise WheelAssetValidationError(
                f"expected exactly one {label} entrypoint; "
                "run `npm run build` before building a wheel"
            )
        entrypoint = candidates[0]
        entrypoints.append(entrypoint)

    try:
        index_text = index.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WheelAssetValidationError("SPA index is not valid UTF-8") from exc
    parser = _SpaIndexParser()
    parser.feed(index_text)
    parser.close()
    if parser.forbidden_inline:
        raise WheelAssetValidationError(
            "SPA index contains CSP-blocked inline content: "
            + ", ".join(parser.forbidden_inline)
        )
    expected_script = f"/assets/{PurePosixPath(entrypoints[0]).name}"
    expected_stylesheet = f"/assets/{PurePosixPath(entrypoints[1]).name}"
    if (
        parser.script_sources != [expected_script]
        or parser.stylesheet_hrefs != [expected_stylesheet]
    ):
        raise WheelAssetValidationError(
            "SPA entrypoint tags must load exactly one hashed JavaScript "
            "and one hashed stylesheet"
        )

    _reject_obsolete_langfuse_session_navigation(assets, location="source")
    _reject_fixed_langfuse_date_range(assets, location="source")
    return tuple(sorted([SPA_INDEX, *entrypoints]))


def validate_wheel_assets(
    wheel: Path | str, source_static: Path | str
) -> tuple[str, ...]:
    """Return sorted wheel entry names after exact name and byte validation."""

    wheel_path = Path(wheel)
    source_static_path = Path(source_static)
    validate_source_spa(source_static_path)
    expected = _source_assets(source_static_path)
    actual = _wheel_assets(wheel_path)
    _reject_obsolete_langfuse_session_navigation(expected, location="source")
    _reject_obsolete_langfuse_session_navigation(actual, location="wheel")
    _reject_fixed_langfuse_date_range(expected, location="source")
    _reject_fixed_langfuse_date_range(actual, location="wheel")

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("extra: " + ", ".join(extra))
        raise WheelAssetValidationError(
            "wheel static asset set differs; " + "; ".join(details)
        )

    changed = sorted(
        name for name in expected if expected[name] != actual[name]
    )
    if changed:
        raise WheelAssetValidationError(
            "wheel static asset content differs: " + ", ".join(changed)
        )

    return tuple(f"{WHEEL_STATIC_PREFIX}{name}" for name in sorted(expected))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight the current SPA build and, when --wheel is provided, "
            "compare every wheel static asset with the current source tree."
        )
    )
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--source-static", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        entrypoints = validate_source_spa(args.source_static)
        if args.wheel is None:
            print("Validated SPA build:")
            for entrypoint in entrypoints:
                print(entrypoint)
            return 0
        entries = validate_wheel_assets(args.wheel, args.source_static)
    except WheelAssetValidationError as exc:
        print(f"Wheel asset validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Validated {len(entries)} static assets:")
    for entry in entries:
        print(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
