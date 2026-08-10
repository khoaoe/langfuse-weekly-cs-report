from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import textwrap
from types import ModuleType
import zipfile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_STATIC = PROJECT_ROOT / "src" / "weekly_cs_report" / "static"
VALIDATOR = PROJECT_ROOT / "scripts" / "verify_wheel_assets.py"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_wheel.sh"
WHEEL_PREFIX = "weekly_cs_report/static/"
VALID_SPA_ASSETS = {
    "spa/index.html": (
        b'<script type="module" src="/assets/index-a1b2c3.js"></script>'
        b'<link rel="stylesheet" href="/assets/index-d4e5f6.css">'
    ),
    "spa/assets/index-a1b2c3.js": b"safe",
    "spa/assets/index-d4e5f6.css": b"safe",
}


def _load_validator() -> ModuleType:
    assert VALIDATOR.is_file(), "wheel asset validator must exist"
    spec = importlib.util.spec_from_file_location("verify_wheel_assets", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_source(static_dir: Path, assets: dict[str, bytes]) -> None:
    for relative, content in assets.items():
        target = static_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _write_wheel(
    wheel: Path,
    assets: dict[str, bytes],
    *,
    duplicate: str | None = None,
    other_entries: dict[str, bytes] | None = None,
) -> None:
    with zipfile.ZipFile(wheel, "w") as archive:
        for relative, content in assets.items():
            archive.writestr(f"{WHEEL_PREFIX}{relative}", content)
        if duplicate is not None:
            archive.writestr(f"{WHEEL_PREFIX}{duplicate}", assets[duplicate])
        for name, content in (other_entries or {}).items():
            archive.writestr(name, content)


def test_validator_accepts_only_an_exact_byte_for_byte_static_tree(tmp_path: Path):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = {
        **VALID_SPA_ASSETS,
        "index.html": b"<!doctype html>",
        "legacy/index.html": b"legacy",
        "spa/assets/brand.woff2": b"\x00\x01font",
    }
    _write_source(static_dir, assets)
    wheel = tmp_path / "dashboard.whl"
    _write_wheel(
        wheel,
        assets,
        other_entries={"weekly_cs_report/web.py": b"# expected package code"},
    )

    assert validator.validate_wheel_assets(wheel, static_dir) == tuple(
        f"{WHEEL_PREFIX}{relative}" for relative in sorted(assets)
    )


@pytest.mark.parametrize(
    ("assets", "message"),
    [
        ({"legacy/index.html": b"legacy"}, "SPA index"),
        (
            {
                "spa/index.html": b'<script src="/assets/index-a1b2c3.js"></script>',
                "spa/assets/index-a1b2c3.js": b"safe",
            },
            "stylesheet",
        ),
        (
            {
                "spa/index.html": (
                    b'<script src="/assets/index.js"></script>'
                    b'<link rel="stylesheet" href="/assets/index.css">'
                ),
                "spa/assets/index.js": b"safe",
                "spa/assets/index.css": b"safe",
            },
            "hashed JavaScript",
        ),
        (
            {
                "spa/index.html": (
                    b"<!-- /assets/index-a1b2c3.js "
                    b"/assets/index-d4e5f6.css -->"
                    b'<script src="/assets/debug.js"></script>'
                    b'<link rel="stylesheet" href="/assets/debug.css">'
                ),
                "spa/assets/index-a1b2c3.js": b"safe",
                "spa/assets/index-d4e5f6.css": b"safe",
                "spa/assets/debug.js": b"safe",
                "spa/assets/debug.css": b"safe",
            },
            "entrypoint tags",
        ),
        (
            {
                "spa/index.html": (
                    b"<style>body { display: none; }</style>"
                    b'<script src="/assets/index-a1b2c3.js"></script>'
                    b'<link rel="stylesheet" href="/assets/index-d4e5f6.css">'
                ),
                "spa/assets/index-a1b2c3.js": b"safe",
                "spa/assets/index-d4e5f6.css": b"safe",
            },
            "inline",
        ),
        (
            {
                "spa/index.html": (
                    b'<body style="display:none" onload="unsafe()">'
                    b'<script src="/assets/index-a1b2c3.js"></script>'
                    b'<link rel="stylesheet" href="/assets/index-d4e5f6.css">'
                    b"</body>"
                ),
                "spa/assets/index-a1b2c3.js": b"safe",
                "spa/assets/index-d4e5f6.css": b"safe",
            },
            "inline",
        ),
        (
            {
                "spa/index.html": (
                    b'<script src="/assets/index-a1b2c3.js"></script>'
                    b'<script src="/assets/debug.js"></script>'
                    b'<link rel="stylesheet" href="/assets/index-d4e5f6.css">'
                ),
                "spa/assets/index-a1b2c3.js": b"safe",
                "spa/assets/index-d4e5f6.css": b"safe",
                "spa/assets/debug.js": b"safe",
            },
            "entrypoint tags",
        ),
    ],
)
def test_source_preflight_rejects_a_missing_or_incomplete_vite_build(
    tmp_path: Path,
    assets: dict[str, bytes],
    message: str,
):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    _write_source(static_dir, assets)

    with pytest.raises(validator.WheelAssetValidationError, match=message):
        validator.validate_source_spa(static_dir)


def test_source_preflight_accepts_referenced_hashed_vite_entrypoints(
    tmp_path: Path,
):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = {
        "spa/index.html": (
            b'<script type="module" src="/assets/index-a1b2c3.js"></script>'
            b'<link rel="stylesheet" href="/assets/index-d4e5f6.css">'
        ),
        "spa/assets/index-a1b2c3.js": b"safe",
        "spa/assets/index-d4e5f6.css": b"safe",
    }
    _write_source(static_dir, assets)

    assert validator.validate_source_spa(static_dir) == (
        "spa/assets/index-a1b2c3.js",
        "spa/assets/index-d4e5f6.css",
        "spa/index.html",
    )


def test_source_preflight_does_not_scan_binary_assets_for_navigation_markers(
    tmp_path: Path,
):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = {
        "spa/index.html": (
            b'<script type="module" src="/assets/index-a1b2c3.js"></script>'
            b'<link rel="stylesheet" href="/assets/index-d4e5f6.css">'
        ),
        "spa/assets/index-a1b2c3.js": b"safe",
        "spa/assets/index-d4e5f6.css": b"safe",
        "spa/assets/brand.woff2": b"\x00/sessions/\x00dateRange=90d\x00",
    }
    _write_source(static_dir, assets)

    assert validator.validate_source_spa(static_dir) == (
        "spa/assets/index-a1b2c3.js",
        "spa/assets/index-d4e5f6.css",
        "spa/index.html",
    )


def test_direct_wheel_validation_cannot_bypass_the_spa_preflight(tmp_path: Path):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = {"index.html": b"legacy only"}
    _write_source(static_dir, assets)
    wheel = tmp_path / "dashboard.whl"
    _write_wheel(wheel, assets)

    with pytest.raises(validator.WheelAssetValidationError, match="SPA index"):
        validator.validate_wheel_assets(wheel, static_dir)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing", "missing"),
        ("extra", "extra"),
        ("changed", "content differs"),
    ],
)
def test_validator_rejects_missing_extra_or_changed_static_assets(
    tmp_path: Path,
    case: str,
    message: str,
):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    source_assets = {**VALID_SPA_ASSETS, "index.html": b"shell"}
    _write_source(static_dir, source_assets)
    wheel = tmp_path / "dashboard.whl"
    if case == "missing":
        wheel_assets = {"index.html": b"shell"}
    elif case == "extra":
        wheel_assets = {
            **source_assets,
            "spa/assets/unexpected.js": b"extra",
        }
    else:
        wheel_assets = {**source_assets, "index.html": b"changed"}
    _write_wheel(wheel, wheel_assets)

    with pytest.raises(validator.WheelAssetValidationError, match=message):
        validator.validate_wheel_assets(wheel, static_dir)


def test_validator_rejects_a_source_map_even_when_source_and_wheel_match(
    tmp_path: Path,
):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = {
        "spa/index.html": b"spa",
        "spa/assets/index.js.map": b'{"version":3}',
    }
    _write_source(static_dir, assets)
    wheel = tmp_path / "dashboard.whl"
    _write_wheel(wheel, assets)

    with pytest.raises(validator.WheelAssetValidationError, match="source map"):
        validator.validate_wheel_assets(wheel, static_dir)


def test_validator_rejects_source_maps_outside_the_static_prefix(tmp_path: Path):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = dict(VALID_SPA_ASSETS)
    _write_source(static_dir, assets)
    wheel = tmp_path / "dashboard.whl"
    _write_wheel(
        wheel,
        assets,
        other_entries={"langfuse_weekly_cs_report-0.1.0.data/app.py.map": b"map"},
    )

    with pytest.raises(validator.WheelAssetValidationError, match="source map"):
        validator.validate_wheel_assets(wheel, static_dir)


@pytest.mark.parametrize(
    "obsolete_navigation",
    [
        b"https://langfuse.example/project/example/sessions/",
        "Mở session ticket 6991254 trên Langfuse".encode(),
    ],
)
def test_validator_rejects_obsolete_langfuse_session_navigation(
    tmp_path: Path,
    obsolete_navigation: bytes,
):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = {
        **VALID_SPA_ASSETS,
        "spa/assets/index-a1b2c3.js": obsolete_navigation,
    }
    _write_source(static_dir, assets)
    wheel = tmp_path / "dashboard.whl"
    _write_wheel(wheel, assets)

    with pytest.raises(
        validator.WheelAssetValidationError,
        match="obsolete Langfuse Session navigation",
    ):
        validator.validate_wheel_assets(wheel, static_dir)


def test_validator_rejects_a_fixed_langfuse_90_day_navigation_range(
    tmp_path: Path,
):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = {
        **VALID_SPA_ASSETS,
        "spa/assets/index-a1b2c3.js": b"/traces?filter=safe&dateRange=90d",
    }
    _write_source(static_dir, assets)
    wheel = tmp_path / "dashboard.whl"
    _write_wheel(wheel, assets)

    with pytest.raises(
        validator.WheelAssetValidationError,
        match="fixed Langfuse 90-day navigation range",
    ):
        validator.validate_wheel_assets(wheel, static_dir)


def test_validator_rejects_duplicate_static_archive_entries(tmp_path: Path):
    validator = _load_validator()
    static_dir = tmp_path / "static"
    assets = dict(VALID_SPA_ASSETS)
    _write_source(static_dir, assets)
    wheel = tmp_path / "dashboard.whl"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_wheel(wheel, assets, duplicate="spa/index.html")

    with pytest.raises(validator.WheelAssetValidationError, match="duplicate"):
        validator.validate_wheel_assets(wheel, static_dir)


def _static_manifest(static_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(static_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(static_dir.rglob("*"))
        if path.is_file()
    }


def _write_fake_uv(fake_bin: Path) -> Path:
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import hashlib
            import json
            import os
            from pathlib import Path
            import sys
            import zipfile

            expected_args = [
                "build",
                "--wheel",
                "--out-dir",
                sys.argv[4],
                "--no-create-gitignore",
                ".",
            ]
            if sys.argv[1:] != expected_args:
                raise SystemExit(f"unexpected uv arguments: {sys.argv[1:]!r}")

            source_root = Path.cwd()
            if {path.name for path in source_root.iterdir()} != {
                "README.md",
                "pyproject.toml",
                "src",
            }:
                raise SystemExit("build did not run in the minimal staged source tree")
            if (source_root / "build").exists() or (source_root / "dist").exists():
                raise SystemExit("stale build output leaked into the staged source tree")

            static_dir = source_root / "src" / "weekly_cs_report" / "static"
            actual = {
                path.relative_to(static_dir).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(static_dir.rglob("*"))
                if path.is_file()
            }
            expected = json.loads(os.environ["EXPECTED_STATIC_MANIFEST"])
            if actual != expected:
                raise SystemExit("staged static tree differs from the current source tree")

            Path(os.environ["FAKE_UV_CWD_RECORD"]).write_text(
                str(source_root), encoding="utf-8"
            )
            out_dir = Path(sys.argv[4])
            wheel = out_dir / "langfuse_weekly_cs_report-0.1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                for path in sorted(static_dir.rglob("*")):
                    if path.is_file():
                        relative = path.relative_to(static_dir).as_posix()
                        archive.writestr(
                            f"weekly_cs_report/static/{relative}", path.read_bytes()
                        )
            """
        ),
        encoding="utf-8",
    )
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)
    return fake_uv


def test_build_script_stages_only_current_sources_and_cleans_its_temp_tree(
    tmp_path: Path,
):
    assert BUILD_SCRIPT.is_file(), "isolated wheel build script must exist"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_uv(fake_bin)
    out_dir = tmp_path / "wheelhouse"
    cwd_record = tmp_path / "uv-cwd.txt"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "EXPECTED_STATIC_MANIFEST": json.dumps(_static_manifest(SOURCE_STATIC)),
        "FAKE_UV_CWD_RECORD": str(cwd_record),
    }

    result = subprocess.run(
        [str(BUILD_SCRIPT), str(out_dir)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert [path.suffix for path in out_dir.iterdir()] == [".whl"]
    staged_source = Path(cwd_record.read_text(encoding="utf-8"))
    assert not staged_source.exists(), "the mktemp staging tree must be removed"
    assert "Validated" in result.stdout


def test_build_script_refuses_a_nonempty_output_directory(tmp_path: Path):
    assert BUILD_SCRIPT.is_file(), "isolated wheel build script must exist"
    out_dir = tmp_path / "wheelhouse"
    out_dir.mkdir()
    sentinel = out_dir / "keep.txt"
    sentinel.write_text("user-owned", encoding="utf-8")

    result = subprocess.run(
        [str(BUILD_SCRIPT), str(out_dir)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "empty" in result.stderr.lower()
    assert sentinel.read_text(encoding="utf-8") == "user-owned"


def test_build_script_has_strict_shell_and_guarded_temp_only_cleanup():
    assert BUILD_SCRIPT.is_file(), "isolated wheel build script must exist"
    text = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "mktemp -d" in text
    assert "trap cleanup EXIT" in text
    assert "weekly-cs-wheel." in text
    assert "rm -rf --" in text
    assert "uv build --wheel" in text
    assert "verify_wheel_assets.py" in text
    assert text.count("--source-static") == 2
    assert text.index("--source-static") < text.index("mktemp -d")
