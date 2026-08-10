#!/usr/bin/env python3
"""Generate deterministic browser fonts from the canonical Aeonik Pro files."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

import brotli
import fontTools
from fontTools.ttLib import TTFont


FONTTOOLS_VERSION = "4.59.1"
BROTLI_VERSION = "1.2.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "assets"
MANIFEST = ASSET_ROOT / "brand-provenance.json"
FONT_PAIRS = {
    "brand/fonts/source/AeonikPro-Regular.otf":
        "brand/fonts/web/aeonik-pro-regular.woff2",
    "brand/fonts/source/AeonikPro-Medium.otf":
        "brand/fonts/web/aeonik-pro-medium.woff2",
    "brand/fonts/source/AeonikPro-Bold.otf":
        "brand/fonts/web/aeonik-pro-bold.woff2",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_pinned_toolchain() -> None:
    if fontTools.__version__ != FONTTOOLS_VERSION:
        raise RuntimeError(
            f"fonttools {FONTTOOLS_VERSION} is required; "
            f"found {fontTools.__version__}"
        )
    if brotli.__version__ != BROTLI_VERSION:
        raise RuntimeError(
            f"brotli {BROTLI_VERSION} is required; found {brotli.__version__}"
        )


def generate_fonts() -> tuple[Path, ...]:
    """Regenerate all WOFF2 files, refusing any unrecorded byte output."""

    _require_pinned_toolchain()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in manifest["files"]}
    generated: list[Path] = []

    for source_name, target_name in FONT_PAIRS.items():
        source = ASSET_ROOT / source_name
        target = ASSET_ROOT / target_name
        if _sha256(source) != entries[source_name]["sha256"]:
            raise RuntimeError(f"canonical font source hash differs: {source_name}")

        font = TTFont(source, recalcTimestamp=False)
        font.flavor = "woff2"
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            font.save(temporary, reorderTables=False)
            if _sha256(temporary) != entries[target_name]["sha256"]:
                raise RuntimeError(
                    f"generated font hash differs from manifest: {target_name}"
                )
            os.replace(temporary, target)
        finally:
            font.close()
            temporary.unlink(missing_ok=True)
        generated.append(target)

    return tuple(generated)


if __name__ == "__main__":
    for generated_font in generate_fonts():
        print(generated_font.relative_to(PROJECT_ROOT))
