"""Parse CS-agent skill markdown snapshots into anchored rule candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_ANCHOR_HEADING = "## Kịch bản & Hướng dẫn"
_HEADING_RE = re.compile(r"^(#{2,3})(?!#)\s+(.*?)\s*$")
_CASE_ID_RE = re.compile(
    r"^(?P<id>[A-Z](?:\.?\d+[a-z]?)(?:\s*,\s*[A-Z]\.?\d+[a-z]?)*)\s+-\s+(?P<title>.+)$"
)
_LEADING_BULLET_RE = re.compile(r"^(?:-\s*)+")

_SKILLS = ("ibft", "topup", "withdraw", "telco", "bank-linking", "bank-unlink")


@dataclass(frozen=True)
class RuleCandidate:
    anchor: str  # "withdraw/references/sub-skill-C.md#L13"
    skill: str  # "withdraw"
    file_label: str  # "sub-skill-C"
    case_id: str | None  # "C1" | None -- display only, never a key
    case_title: str
    body: str  # verbatim case block
    source: str  # "sub_skill" | "skill_md" | "tool_message"


def _heading_level(line: str) -> int | None:
    match = _HEADING_RE.match(line)
    return len(match.group(1)) if match else None


def _find_anchor_line(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == _ANCHOR_HEADING:
            return index
    return None


def _case_body(lines: list[str], start: int) -> tuple[str, int]:
    """Return (body, next_index) scanning from start until the next heading/EOF."""

    end = start
    while end < len(lines) and _heading_level(lines[end]) is None:
        end += 1
    body = "\n".join(lines[start:end]).strip("\n")
    return body, end


def _parse_sub_skill(
    lines: list[str], rel_path: str, skill: str, file_label: str
) -> list[RuleCandidate]:
    # Five snapshot files carry no "## Kịch bản & Hướng dẫn" line and start their
    # cases straight after "## Tool bổ sung"; scanning from the top keeps them.
    anchor_line = _find_anchor_line(lines)
    scan_start = anchor_line + 1 if anchor_line is not None else 0

    candidates: list[RuleCandidate] = []
    index = scan_start
    total = len(lines)
    while index < total:
        if _heading_level(lines[index]) == 3:
            heading_text = _HEADING_RE.match(lines[index]).group(2)
            case_match = _CASE_ID_RE.match(heading_text)
            if case_match:
                case_id = case_match.group("id")
                case_title = case_match.group("title").strip()
            else:
                case_id = None
                case_title = heading_text
            body, next_index = _case_body(lines, index + 1)
            candidates.append(
                RuleCandidate(
                    anchor=f"{rel_path}#L{index + 1}",
                    skill=skill,
                    file_label=file_label,
                    case_id=case_id,
                    case_title=case_title,
                    body=body,
                    source="sub_skill",
                )
            )
            index = next_index
        else:
            index += 1
    return candidates


def _parse_skill_md(
    lines: list[str], rel_path: str, skill: str, file_label: str
) -> list[RuleCandidate]:
    candidates: list[RuleCandidate] = []
    index = 0
    total = len(lines)
    while index < total:
        if _heading_level(lines[index]) == 2:
            case_title = _HEADING_RE.match(lines[index]).group(2)
            body, next_index = _case_body(lines, index + 1)
            candidates.append(
                RuleCandidate(
                    anchor=f"{rel_path}#L{index + 1}",
                    skill=skill,
                    file_label=file_label,
                    case_id=None,
                    case_title=case_title,
                    body=body,
                    source="skill_md",
                )
            )
            index = next_index
        else:
            index += 1
    return candidates


def parse_skill_file(path: Path, rel_path: str) -> list[RuleCandidate]:
    """Parse one skill markdown file into its rule candidates.

    `rel_path` is the POSIX path used to build anchors, e.g.
    "withdraw/references/sub-skill-C.md" or "withdraw/SKILL.md".
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    parts = rel_path.split("/")
    skill = parts[0]
    file_label = Path(parts[-1]).stem
    if parts[-1] == "SKILL.md":
        return _parse_skill_md(lines, rel_path, skill, file_label)
    return _parse_sub_skill(lines, rel_path, skill, file_label)


def parse_snapshot(root: Path) -> dict[str, list[RuleCandidate]]:
    """Parse every skill in the snapshot store; key = skill name."""

    result: dict[str, list[RuleCandidate]] = {}
    for skill in _SKILLS:
        skill_root = root / skill
        if not skill_root.is_dir():
            continue
        candidates: list[RuleCandidate] = []
        skill_md = skill_root / "SKILL.md"
        if skill_md.is_file():
            candidates.extend(parse_skill_file(skill_md, f"{skill}/SKILL.md"))
        references_dir = skill_root / "references"
        if references_dir.is_dir():
            for sub_skill_path in sorted(references_dir.glob("sub-skill-*.md")):
                rel_path = f"{skill}/references/{sub_skill_path.name}"
                candidates.extend(parse_skill_file(sub_skill_path, rel_path))
        result[skill] = candidates
    return result


def extract_line(candidate: RuleCandidate, line_index: int) -> str | None:
    """Return the verbatim (bullet-stripped) text of one line in a case body."""

    lines = candidate.body.split("\n")
    if not 0 <= line_index < len(lines):
        return None
    text = _LEADING_BULLET_RE.sub("", lines[line_index]).strip()
    return text or None
