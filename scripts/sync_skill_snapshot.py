#!/usr/bin/env python3
"""Sync CS-agent skill markdown from ../docs/cs-agent-skills into skills-snapshot/."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

_SKILLS = ("ibft", "topup", "withdraw", "telco", "bank-linking", "bank-unlink")


class SkillSnapshotError(RuntimeError):
    """Raised when the skill source tree cannot be synced."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_files(skill_root: Path) -> list[Path]:
    skill_md = skill_root / "SKILL.md"
    if not skill_md.is_file():
        raise SkillSnapshotError(f"missing SKILL.md: {skill_md}")
    files = [skill_md]
    references_dir = skill_root / "references"
    if references_dir.is_dir():
        files.extend(sorted(references_dir.glob("sub-skill-*.md")))
    return files


def sync_skill_snapshot(source_root: Path, snapshot_root: Path) -> dict[str, object]:
    """Copy skill markdown from source_root into snapshot_root; return provenance."""

    if not source_root.is_dir():
        raise SkillSnapshotError(f"skill source root does not exist: {source_root}")

    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    snapshot_root.mkdir(parents=True)

    manifest_files: dict[str, dict[str, str]] = {}
    for skill in _SKILLS:
        skill_root = source_root / skill
        for source_file in _skill_files(skill_root):
            relative = source_file.relative_to(source_root)
            dest = snapshot_root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, dest)
            manifest_files[relative.as_posix()] = {"sha256": _sha256(dest)}

    provenance = {
        "synced_at": date.today().isoformat(),
        "source": "../docs/cs-agent-skills",
        "files": manifest_files,
    }
    (snapshot_root / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("../docs/cs-agent-skills")
    )
    parser.add_argument(
        "--snapshot-root", type=Path, default=Path("skills-snapshot")
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        provenance = sync_skill_snapshot(args.source, args.snapshot_root)
    except SkillSnapshotError as exc:
        print(f"Skill snapshot sync failed: {exc}", file=sys.stderr)
        return 1
    print(f"Synced {len(provenance['files'])} skill files into {args.snapshot_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
