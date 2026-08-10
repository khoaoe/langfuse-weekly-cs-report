#!/usr/bin/env python3
"""Verify project brand assets and their canonical-source provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any


class BrandAssetValidationError(ValueError):
    """Raised when the brand asset store cannot prove its manifest."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BrandAssetValidationError(f"unsafe {label}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BrandAssetValidationError(f"unsafe {label}: {value!r}")
    return path


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrandAssetValidationError(
            f"cannot read brand manifest: {manifest_path}"
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise BrandAssetValidationError("unsupported brand manifest schema")
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise BrandAssetValidationError("brand manifest has no files")
    return manifest


def validate_brand_assets(
    manifest_path: Path | str,
    asset_root: Path | str,
    canonical_root: Path | str | None = None,
) -> tuple[str, ...]:
    """Return verified asset paths after hash, inventory and provenance checks."""

    manifest = _load_manifest(Path(manifest_path))
    root = Path(asset_root)
    canonical = None if canonical_root is None else Path(canonical_root)
    if not root.is_dir():
        raise BrandAssetValidationError(f"asset root does not exist: {root}")
    if canonical is not None and not canonical.is_dir():
        raise BrandAssetValidationError(
            f"canonical guideline root does not exist: {canonical}"
        )

    verified: list[str] = []
    seen: set[str] = set()
    for raw_entry in manifest["files"]:
        if not isinstance(raw_entry, dict):
            raise BrandAssetValidationError("brand manifest entry must be an object")
        relative = _safe_relative(raw_entry.get("path"), label="asset path")
        name = relative.as_posix()
        if name in seen:
            raise BrandAssetValidationError(f"duplicate asset path: {name}")
        seen.add(name)

        expected_hash = raw_entry.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise BrandAssetValidationError(f"invalid asset hash: {name}")
        asset = root.joinpath(*relative.parts)
        if not asset.is_file():
            raise BrandAssetValidationError(f"asset is missing: {name}")
        if _sha256(asset) != expected_hash:
            raise BrandAssetValidationError(f"asset hash differs: {name}")

        source_relative = _safe_relative(
            raw_entry.get("canonical_source"), label="canonical source path"
        )
        canonical_hash = raw_entry.get("canonical_sha256")
        if not isinstance(canonical_hash, str) or len(canonical_hash) != 64:
            raise BrandAssetValidationError(f"invalid canonical hash: {name}")
        if canonical is not None:
            source = canonical.joinpath(*source_relative.parts)
            if not source.is_file():
                raise BrandAssetValidationError(
                    f"canonical source is missing: {source_relative}"
                )
            if _sha256(source) != canonical_hash:
                raise BrandAssetValidationError(
                    f"canonical source hash differs: {source_relative}"
                )
            if (
                raw_entry.get("derivation") == "exact-copy"
                and asset.read_bytes() != source.read_bytes()
            ):
                raise BrandAssetValidationError(
                    f"exact-copy asset differs from canonical source: {name}"
                )
        verified.append(name)

    brand_root = root / "brand"
    symlinks = sorted(
        path.relative_to(root).as_posix()
        for path in brand_root.rglob("*")
        if path.is_symlink()
    )
    if symlinks:
        raise BrandAssetValidationError(
            "asset store contains symlinks: " + ", ".join(symlinks)
        )

    present = {
        path.relative_to(root).as_posix()
        for path in brand_root.rglob("*")
        if path.is_file()
    }
    if present != seen:
        missing = sorted(seen - present)
        extra = sorted(present - seen)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unmanifested: " + ", ".join(extra))
        raise BrandAssetValidationError(
            "brand asset inventory differs; " + "; ".join(details)
        )

    forbidden = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".ai", ".pdf"}
    )
    if forbidden:
        raise BrandAssetValidationError(
            "browser-inappropriate source files found: " + ", ".join(forbidden)
        )
    return tuple(sorted(verified))


def validate_asset_inventory(
    manifest_paths: tuple[Path | str, ...],
    asset_root: Path | str,
) -> tuple[str, ...]:
    """Validate all first- and third-party asset manifests as one inventory."""

    root = Path(asset_root)
    if not root.is_dir():
        raise BrandAssetValidationError(f"asset root does not exist: {root}")

    manifest_files = {Path(path).resolve() for path in manifest_paths}
    expected: set[str] = set()
    for manifest_path in manifest_paths:
        manifest = _load_manifest(Path(manifest_path))
        for raw_entry in manifest["files"]:
            if not isinstance(raw_entry, dict):
                raise BrandAssetValidationError(
                    "asset manifest entry must be an object"
                )
            relative = _safe_relative(raw_entry.get("path"), label="asset path")
            name = relative.as_posix()
            if name in expected:
                raise BrandAssetValidationError(
                    f"asset appears in more than one manifest: {name}"
                )
            expected.add(name)
            expected_hash = raw_entry.get("sha256")
            if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                raise BrandAssetValidationError(f"invalid asset hash: {name}")
            asset = root.joinpath(*relative.parts)
            if not asset.is_file():
                raise BrandAssetValidationError(f"asset is missing: {name}")
            if _sha256(asset) != expected_hash:
                raise BrandAssetValidationError(f"asset hash differs: {name}")

    symlinks = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_symlink()
    )
    if symlinks:
        raise BrandAssetValidationError(
            "asset store contains symlinks: " + ", ".join(symlinks)
        )
    present = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() not in manifest_files
    }
    if present != expected:
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unmanifested: " + ", ".join(extra))
        raise BrandAssetValidationError(
            "global asset inventory differs; " + "; ".join(details)
        )
    forbidden = sorted(
        name for name in present if Path(name).suffix.lower() in {".ai", ".pdf"}
    )
    if forbidden:
        raise BrandAssetValidationError(
            "browser-inappropriate source files found: " + ", ".join(forbidden)
        )
    return tuple(sorted(expected))


def validate_built_brand_assets(
    manifest_path: Path | str,
    asset_root: Path | str,
    built_asset_root: Path | str,
) -> tuple[str, ...]:
    """Prove that Vite emitted browser assets once and excluded source files."""

    validate_brand_assets(manifest_path, asset_root)
    manifest = _load_manifest(Path(manifest_path))
    built_root = Path(built_asset_root)
    if not built_root.is_dir():
        raise BrandAssetValidationError(
            f"built asset root does not exist: {built_root}"
        )

    built_files = [path for path in built_root.rglob("*") if path.is_file()]
    forbidden = sorted(
        path.relative_to(built_root).as_posix()
        for path in built_files
        if path.suffix.lower() in {".otf", ".ai", ".pdf"}
    )
    if forbidden:
        raise BrandAssetValidationError(
            "source-only asset leaked into browser bundle: " + ", ".join(forbidden)
        )

    files_by_hash: dict[str, list[Path]] = {}
    for path in built_files:
        files_by_hash.setdefault(_sha256(path), []).append(path)

    emitted: list[str] = []
    for entry in manifest["files"]:
        matches = files_by_hash.get(entry["sha256"], [])
        if entry.get("browser") is True:
            if not matches:
                raise BrandAssetValidationError(
                    f"browser asset is missing from bundle: {entry['path']}"
                )
            if len(matches) != 1:
                raise BrandAssetValidationError(
                    f"browser asset was emitted more than once: {entry['path']}"
                )
            emitted.append(matches[0].relative_to(built_root).as_posix())
        elif matches:
            raise BrandAssetValidationError(
                f"source-only asset leaked into browser bundle: {entry['path']}"
            )

    return tuple(sorted(emitted))


def validate_built_asset_inventory(
    manifest_paths: tuple[Path | str, ...],
    asset_root: Path | str,
    built_asset_root: Path | str,
) -> tuple[str, ...]:
    """Prove that all curated browser assets, including third-party, shipped."""

    validate_asset_inventory(manifest_paths, asset_root)
    built_root = Path(built_asset_root)
    if not built_root.is_dir():
        raise BrandAssetValidationError(
            f"built asset root does not exist: {built_root}"
        )

    built_files = [path for path in built_root.rglob("*") if path.is_file()]
    forbidden = sorted(
        path.relative_to(built_root).as_posix()
        for path in built_files
        if path.suffix.lower() in {".otf", ".ai", ".pdf"}
    )
    if forbidden:
        raise BrandAssetValidationError(
            "source-only asset leaked into browser bundle: " + ", ".join(forbidden)
        )

    files_by_hash: dict[str, list[Path]] = {}
    for path in built_files:
        files_by_hash.setdefault(_sha256(path), []).append(path)

    emitted: list[str] = []
    for manifest_path in manifest_paths:
        manifest = _load_manifest(Path(manifest_path))
        for entry in manifest["files"]:
            matches = files_by_hash.get(entry["sha256"], [])
            if entry.get("browser") is True:
                if not matches:
                    raise BrandAssetValidationError(
                        f"browser asset is missing from bundle: {entry['path']}"
                    )
                if len(matches) != 1:
                    raise BrandAssetValidationError(
                        f"browser asset was emitted more than once: {entry['path']}"
                    )
                emitted.append(matches[0].relative_to(built_root).as_posix())
            elif matches:
                raise BrandAssetValidationError(
                    f"source-only asset leaked into browser bundle: {entry['path']}"
                )

    return tuple(sorted(emitted))


def _parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Verify brand asset hashes and canonical guideline provenance."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project_root / "assets" / "brand-provenance.json",
    )
    parser.add_argument(
        "--asset-root", type=Path, default=project_root / "assets"
    )
    parser.add_argument("--canonical-root", type=Path)
    parser.add_argument(
        "--require-canonical",
        action="store_true",
        help="Fail unless --canonical-root is available for a live source audit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    canonical = args.canonical_root
    if canonical is None:
        manifest = _load_manifest(args.manifest)
        hint = manifest.get("canonical_root_hint")
        if isinstance(hint, str):
            candidate = args.manifest.parents[1] / hint
            if candidate.is_dir():
                canonical = candidate
    if args.require_canonical and canonical is None:
        print(
            "Brand asset validation failed: canonical guideline root is unavailable",
            file=sys.stderr,
        )
        return 1
    try:
        brand_assets = validate_brand_assets(
            args.manifest, args.asset_root, canonical
        )
        inventory_manifests: tuple[Path, ...] = (args.manifest,)
        third_party = args.asset_root / "third-party-provenance.json"
        if third_party.is_file():
            inventory_manifests += (third_party,)
        assets = validate_asset_inventory(inventory_manifests, args.asset_root)
    except BrandAssetValidationError as exc:
        print(f"Brand asset validation failed: {exc}", file=sys.stderr)
        return 1
    audit = "with canonical source" if canonical is not None else "from pinned hashes"
    print(
        f"Validated {len(brand_assets)} Zalopay brand assets {audit}; "
        f"{len(assets)} total curated assets."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
