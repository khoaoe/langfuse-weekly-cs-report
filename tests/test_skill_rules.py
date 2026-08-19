from __future__ import annotations

from pathlib import Path

from weekly_cs_report import skill_rules

SNAPSHOT_ROOT = Path(__file__).parents[1] / "skills-snapshot"


def _parse(rel_path: str) -> list[skill_rules.RuleCandidate]:
    return skill_rules.parse_skill_file(SNAPSHOT_ROOT / rel_path, rel_path)


def test_dotted_case_id_ibft_sub_skill_e():
    candidates = _parse("ibft/references/sub-skill-E.md")
    assert len(candidates) >= 12
    assert all(c.case_id and "." in c.case_id for c in candidates)


def test_two_ids_one_heading_collapse_to_one_case():
    candidates = _parse("ibft/references/sub-skill-CD.md")
    two_id_cases = [c for c in candidates if c.case_id == "D1, D2"]
    assert len(two_id_cases) == 1


def test_missing_case_id_still_produces_case():
    candidates = _parse("topup/references/sub-skill-D.md")
    assert len(candidates) == 2
    assert all(c.case_id is None for c in candidates)
    assert all(c.case_title for c in candidates)


def test_duplicate_case_id_keeps_anchor_unique():
    candidates = _parse("topup/references/sub-skill-B.md")
    assert len(candidates) == 3
    assert [c.case_id for c in candidates] == ["B1", "B2", "B2"]
    assert len({c.anchor for c in candidates}) == 3


def test_skill_md_numbered_section_parsed():
    candidates = _parse("withdraw/SKILL.md")
    titles = [c.case_title for c in candidates]
    assert "5. Gửi lên bộ phận CSKH" in titles
    assert all(c.source == "skill_md" and c.case_id is None for c in candidates)


def test_anchor_optional_for_files_without_scenario_heading():
    # ibft/sub-skill-E.md and sub-skill-FGH.md have no "## Kịch bản & Hướng dẫn"
    # line at all; cases still parse from every top-level ### heading.
    fgh = _parse("ibft/references/sub-skill-FGH.md")
    assert len(fgh) == 10
    assert [c.case_id for c in fgh][:3] == ["F1", "F2", "F3"]


def test_extract_line_strips_bullet_markers():
    candidates = _parse("withdraw/references/sub-skill-C.md")
    c1 = next(c for c in candidates if c.case_id == "C1")
    lines = c1.body.split("\n")
    nested_index = next(
        i for i, line in enumerate(lines) if line.startswith("- - Nếu đã quá")
    )
    quoted = skill_rules.extract_line(c1, nested_index)
    assert quoted == "Nếu đã quá 3 ngày: Chuyển bộ phận CSKH"
    assert skill_rules.extract_line(c1, len(lines) + 5) is None


def test_global_anchor_uniqueness_across_snapshot():
    all_candidates = skill_rules.parse_snapshot(SNAPSHOT_ROOT)
    anchors = [c.anchor for candidates in all_candidates.values() for c in candidates]
    assert len(anchors) == len(set(anchors))
    assert len(anchors) > 0


def test_every_scenario_heading_file_yields_at_least_one_case():
    all_candidates = skill_rules.parse_snapshot(SNAPSHOT_ROOT)
    for skill, candidates in all_candidates.items():
        by_file: dict[str, int] = {}
        for c in candidates:
            by_file[c.file_label] = by_file.get(c.file_label, 0) + 1
        assert all(count > 0 for count in by_file.values()), (skill, by_file)


def test_parse_snapshot_covers_all_six_skills():
    all_candidates = skill_rules.parse_snapshot(SNAPSHOT_ROOT)
    assert set(all_candidates) == {
        "ibft",
        "topup",
        "withdraw",
        "telco",
        "bank-linking",
        "bank-unlink",
    }
