#!/usr/bin/env python3
"""Verify the CS-agent skills-snapshot store against its provenance manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


class SkillSnapshotValidationError(ValueError):
    """Raised when the skill snapshot cannot prove its provenance."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_provenance(path: Path) -> dict[str, object]:
    try:
        provenance = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillSnapshotValidationError(f"cannot read provenance: {path}") from exc
    files = provenance.get("files")
    if not isinstance(files, dict) or not files:
        raise SkillSnapshotValidationError("provenance has no files")
    return provenance


def verify_skill_snapshot(
    snapshot_root: Path, source_root: Path | None = None
) -> tuple[str, ...]:
    """Verify every snapshot file matches its pinned hash; return verified paths."""

    if not snapshot_root.is_dir():
        raise SkillSnapshotValidationError(
            f"snapshot root does not exist: {snapshot_root}"
        )
    provenance = _load_provenance(snapshot_root / "provenance.json")
    files = provenance["files"]

    verified: list[str] = []
    for relative_name, entry in files.items():
        expected_hash = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise SkillSnapshotValidationError(f"invalid hash entry: {relative_name}")
        path = snapshot_root / relative_name
        if not path.is_file():
            raise SkillSnapshotValidationError(
                f"snapshot file missing: {relative_name}"
            )
        if _sha256(path) != expected_hash:
            raise SkillSnapshotValidationError(
                f"snapshot hash differs: {relative_name}"
            )
        if source_root is not None:
            source_path = source_root / relative_name
            if source_path.is_file() and _sha256(source_path) != expected_hash:
                raise SkillSnapshotValidationError(
                    f"snapshot is stale versus source: {relative_name}"
                )
        verified.append(relative_name)

    present = {
        path.relative_to(snapshot_root).as_posix()
        for path in snapshot_root.rglob("*.md")
    }
    manifested = set(files)
    if present != manifested:
        missing = sorted(manifested - present)
        extra = sorted(present - manifested)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unmanifested: " + ", ".join(extra))
        raise SkillSnapshotValidationError(
            "skill snapshot inventory differs; " + "; ".join(details)
        )
    return tuple(sorted(verified))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-root", type=Path, default=Path("skills-snapshot")
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="optional sibling ../docs/cs-agent-skills to check for drift",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verified = verify_skill_snapshot(args.snapshot_root, args.source)
    except SkillSnapshotValidationError as exc:
        print(f"Skill snapshot validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified {len(verified)} skill snapshot files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
