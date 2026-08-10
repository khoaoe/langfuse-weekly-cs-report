from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "assets"
BRAND_ROOT = ASSET_ROOT / "brand"
MANIFEST = ASSET_ROOT / "brand-provenance.json"
THIRD_PARTY_MANIFEST = ASSET_ROOT / "third-party-provenance.json"
CANONICAL_ROOT = PROJECT_ROOT.parent / "docs" / "zalopay-guideline"
VALIDATOR = PROJECT_ROOT / "scripts" / "verify_brand_assets.py"

EXPECTED_FILES = {
    "brand/icons/zalopay-app-icon.png": {
        "canonical_source": "Zalopay_LogoPNG/Logo FA-13.png",
        "canonical_sha256": "970c4738c333dac4c22184b55477f6ce8089a11d128e33858d543ef1e10a553e",
        "sha256": "970c4738c333dac4c22184b55477f6ce8089a11d128e33858d543ef1e10a553e",
        "browser": True,
        "derivation": "exact-copy",
    },
    "brand/logos/zalopay-logo-color.png": {
        "canonical_source": "Zalopay_LogoPNG/Logo FA-09.png",
        "canonical_sha256": "6f401d0089ffce4d4069638e57bd6e4f16b9cdbb6fbe5ed412353e9217001dc5",
        "sha256": "6f401d0089ffce4d4069638e57bd6e4f16b9cdbb6fbe5ed412353e9217001dc5",
        "browser": True,
        "derivation": "exact-copy",
    },
    "brand/logos/zalopay-logo-white.png": {
        "canonical_source": "Zalopay_LogoPNG/Logo FA-10.png",
        "canonical_sha256": "a778739822f1f44d3ce0779d019b90f2e38d4575705e72fe0045895c3c60e2da",
        "sha256": "a778739822f1f44d3ce0779d019b90f2e38d4575705e72fe0045895c3c60e2da",
        "browser": True,
        "derivation": "exact-copy",
    },
    "brand/graphics/zalopay-z-dark.png": {
        "canonical_source": "png/visual-43.png",
        "canonical_sha256": "968a9b22fb3fc99424160184dfd80215cc7cca9f124c5ba456c56a85e8faccec",
        "sha256": "968a9b22fb3fc99424160184dfd80215cc7cca9f124c5ba456c56a85e8faccec",
        "browser": True,
        "derivation": "exact-copy",
    },
    "brand/graphics/zalopay-z-light.png": {
        "canonical_source": "png/visual-42.png",
        "canonical_sha256": "8a5a40e6781a8b3fe281e5c549bb5b2e56245d2226d0cf212fc00a2d51c2dae2",
        "sha256": "8a5a40e6781a8b3fe281e5c549bb5b2e56245d2226d0cf212fc00a2d51c2dae2",
        "browser": True,
        "derivation": "exact-copy",
    },
    "brand/fonts/source/AeonikPro-Regular.otf": {
        "canonical_source": "Aeonik Pro - font final/AeonikPro-Regular.otf",
        "canonical_sha256": "6c502f426b9b21b7e19c8497f8da932274ecd887fa6c33fd28838ffb08b5681c",
        "sha256": "6c502f426b9b21b7e19c8497f8da932274ecd887fa6c33fd28838ffb08b5681c",
        "browser": False,
        "derivation": "exact-copy",
    },
    "brand/fonts/source/AeonikPro-Medium.otf": {
        "canonical_source": "Aeonik Pro - font final/AeonikPro-Medium.otf",
        "canonical_sha256": "dbe566d2341103c848f1f2371340602e9017b94cc8ea87fa05cb2c7fa9fa941a",
        "sha256": "dbe566d2341103c848f1f2371340602e9017b94cc8ea87fa05cb2c7fa9fa941a",
        "browser": False,
        "derivation": "exact-copy",
    },
    "brand/fonts/source/AeonikPro-Bold.otf": {
        "canonical_source": "Aeonik Pro - font final/AeonikPro-Bold.otf",
        "canonical_sha256": "32c7901a508fa12224d1cb63222270ec2d88b865e1dc2a07f5be7ede106fdd56",
        "sha256": "32c7901a508fa12224d1cb63222270ec2d88b865e1dc2a07f5be7ede106fdd56",
        "browser": False,
        "derivation": "exact-copy",
    },
    "brand/fonts/web/aeonik-pro-regular.woff2": {
        "canonical_source": "Aeonik Pro - font final/AeonikPro-Regular.otf",
        "canonical_sha256": "6c502f426b9b21b7e19c8497f8da932274ecd887fa6c33fd28838ffb08b5681c",
        "sha256": "61810ab932aa9c2e7aded4f225ab5e614d91e5bdfe60e8cb20efc5b4011f1f8f",
        "browser": True,
        "derivation": "woff2",
    },
    "brand/fonts/web/aeonik-pro-medium.woff2": {
        "canonical_source": "Aeonik Pro - font final/AeonikPro-Medium.otf",
        "canonical_sha256": "dbe566d2341103c848f1f2371340602e9017b94cc8ea87fa05cb2c7fa9fa941a",
        "sha256": "fb0a13c1e3e5329dcb5a649659558cbc2be61460a2b94be57fa1f5b745a16053",
        "browser": True,
        "derivation": "woff2",
    },
    "brand/fonts/web/aeonik-pro-bold.woff2": {
        "canonical_source": "Aeonik Pro - font final/AeonikPro-Bold.otf",
        "canonical_sha256": "32c7901a508fa12224d1cb63222270ec2d88b865e1dc2a07f5be7ede106fdd56",
        "sha256": "4a05776a68698a73109e554dac8bf2164163b60b1bffedc1e309dc3bb4aa230c",
        "browser": True,
        "derivation": "woff2",
    },
}

EXPECTED_THIRD_PARTY_FILES = {
    "icons/langfuse-icon.svg": {
        "provider": "Langfuse",
        "source_url": (
            "https://langfuse.com/brand-assets/icon/color/langfuse-icon.svg"
        ),
        "source_sha256": "daeef880d58644fab4fd9ba5d292086c6d69756a39cff94d510f8ddc35312bf3",
        "sha256": "daeef880d58644fab4fd9ba5d292086c6d69756a39cff94d510f8ddc35312bf3",
        "browser": True,
        "derivation": "exact-copy",
    }
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_validator() -> ModuleType:
    assert VALIDATOR.is_file(), "brand asset validator must exist"
    spec = importlib.util.spec_from_file_location("verify_brand_assets", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_brand_manifest_pins_every_asset_to_the_canonical_guideline():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert manifest["canonical_root_hint"] == "../docs/zalopay-guideline"
    assert manifest["font_conversion"] == {
        "script": "scripts/generate_brand_fonts.py",
        "fonttools": "4.59.1",
        "brotli": "1.2.0",
        "recalc_timestamp": False,
        "reorder_tables": False,
    }
    assert {entry["path"]: {key: entry[key] for key in EXPECTED_FILES[entry["path"]]} for entry in manifest["files"]} == EXPECTED_FILES


def test_brand_store_contains_only_manifested_used_assets_with_expected_hashes():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected_paths = set(EXPECTED_FILES)
    present_paths = {
        path.relative_to(ASSET_ROOT).as_posix()
        for path in BRAND_ROOT.rglob("*")
        if path.is_file()
    }

    assert present_paths == expected_paths
    assert {entry["path"] for entry in manifest["files"]} == expected_paths
    for relative, expected in EXPECTED_FILES.items():
        assert _sha256(ASSET_ROOT / relative) == expected["sha256"]

    assert not any(
        path.suffix.lower() in {".ai", ".pdf"}
        for path in ASSET_ROOT.rglob("*")
        if path.is_file()
    )


def test_exact_copies_still_match_the_available_canonical_source_byte_for_byte():
    if not CANONICAL_ROOT.is_dir():
        pytest.skip("sibling canonical guideline is unavailable in this checkout")
    for relative, expected in EXPECTED_FILES.items():
        canonical = CANONICAL_ROOT / expected["canonical_source"]
        assert _sha256(canonical) == expected["canonical_sha256"]
        if expected["derivation"] == "exact-copy":
            assert (ASSET_ROOT / relative).read_bytes() == canonical.read_bytes()


def test_frontend_references_only_the_browser_assets_in_the_project_store():
    shell = (PROJECT_ROOT / "frontend/src/components/AppShell.tsx").read_text(
        encoding="utf-8"
    )
    styles = (PROJECT_ROOT / "frontend/src/styles/global.css").read_text(
        encoding="utf-8"
    )
    index = (PROJECT_ROOT / "frontend/index.html").read_text(encoding="utf-8")

    assert not (PROJECT_ROOT / "frontend/src/assets").exists()
    assert "../../../assets/brand/logos/zalopay-logo-color.png" in shell
    assert "../../../assets/brand/logos/zalopay-logo-white.png" in shell
    for weight in ("regular", "medium", "bold"):
        assert f'../../../assets/brand/fonts/web/aeonik-pro-{weight}.woff2' in styles
    assert "../assets/brand/icons/zalopay-app-icon.png" in index
    assert "../../../assets/brand/graphics/zalopay-z-light.png" in shell
    assert "../../../assets/brand/graphics/zalopay-z-dark.png" in shell


def test_browser_font_payload_stays_within_the_approved_budget():
    browser_fonts = [
        ASSET_ROOT / relative
        for relative, metadata in EXPECTED_FILES.items()
        if metadata["browser"] and relative.endswith(".woff2")
    ]

    assert sum(path.stat().st_size for path in browser_fonts) <= 300_000


def test_production_bundle_contains_every_browser_asset_and_no_source_font():
    validator = _load_validator()
    built_assets = (
        PROJECT_ROOT / "src/weekly_cs_report/static/spa/assets"
    )

    emitted = validator.validate_built_asset_inventory(
        (MANIFEST, THIRD_PARTY_MANIFEST), ASSET_ROOT, built_assets
    )

    assert len(emitted) == 9
    assert all(
        name.endswith((".png", ".svg", ".woff2"))
        for name in emitted
    )
    assert not any(name.endswith((".otf", ".ai", ".pdf")) for name in emitted)


def test_third_party_manifest_keeps_the_langfuse_icon_outside_zalopay_brand():
    manifest = json.loads(THIRD_PARTY_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert {
        entry["path"]: {
            key: entry[key] for key in EXPECTED_THIRD_PARTY_FILES[entry["path"]]
        }
        for entry in manifest["files"]
    } == EXPECTED_THIRD_PARTY_FILES
    assert not any(
        relative in EXPECTED_FILES for relative in EXPECTED_THIRD_PARTY_FILES
    )
    for relative, expected in EXPECTED_THIRD_PARTY_FILES.items():
        assert _sha256(ASSET_ROOT / relative) == expected["sha256"]


def test_global_asset_inventory_rejects_every_unmanifested_file():
    validator = _load_validator()

    assert validator.validate_asset_inventory(
        (MANIFEST, THIRD_PARTY_MANIFEST), ASSET_ROOT
    ) == tuple(sorted(EXPECTED_FILES | EXPECTED_THIRD_PARTY_FILES))


def test_validator_rejects_hash_drift_and_path_traversal(tmp_path: Path):
    validator = _load_validator()
    assets = tmp_path / "assets"
    (assets / "brand").mkdir(parents=True)
    (assets / "brand/asset.bin").write_bytes(b"drifted")
    manifest = {
        "schema_version": 1,
        "files": [
            {
                "path": "brand/asset.bin",
                "canonical_source": "source.bin",
                "canonical_sha256": hashlib.sha256(b"canonical").hexdigest(),
                "sha256": hashlib.sha256(b"expected").hexdigest(),
                "browser": True,
                "derivation": "exact-copy",
            }
        ],
    }
    manifest_path = assets / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(validator.BrandAssetValidationError, match="hash differs"):
        validator.validate_brand_assets(manifest_path, assets)

    manifest["files"][0]["path"] = "../outside.bin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(validator.BrandAssetValidationError, match="unsafe asset path"):
        validator.validate_brand_assets(manifest_path, assets)

    manifest["files"][0]["path"] = "brand/asset.bin"
    manifest["files"][0]["sha256"] = hashlib.sha256(b"drifted").hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (assets / "brand/stray.svg").write_text("<svg/>", encoding="utf-8")
    with pytest.raises(
        validator.BrandAssetValidationError,
        match="unmanifested: brand/stray.svg",
    ):
        validator.validate_brand_assets(manifest_path, assets)
