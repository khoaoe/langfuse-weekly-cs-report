from __future__ import annotations

import pytest

from weekly_cs_report import narration_validator as validator
from weekly_cs_report.escalation_dossier import (
    CoverageCheck,
    EscalationDossier,
    ToolEvidence,
)
from weekly_cs_report.escalation_narrator import BangChungItem, CanCu, Narration
from weekly_cs_report.skill_rules import RuleCandidate

_CANDIDATE = RuleCandidate(
    anchor="withdraw/references/sub-skill-C.md#L13",
    skill="withdraw",
    file_label="sub-skill-C",
    case_id="C1",
    case_title="Giao dịch đang xử lý",
    body="- Nếu đã quá 3 ngày: Chuyển bộ phận CSKH",
    source="sub_skill",
)


def _dossier(rule_candidates=(_CANDIDATE,), tool_evidence=None) -> EscalationDossier:
    return EscalationDossier(
        ticket_id="9001001",
        escalation_class="E1",
        escalated_turn=0,
        guardrail_reason=None,
        blocking_rule="cs_escalation",
        skills_loaded=("withdraw",),
        sub_skills_read=("sub-skill-C.md",),
        tool_evidence=tool_evidence
        if tool_evidence is not None
        else (
            ToolEvidence(
                step_key="tool:calculate_time_difference__withdraw",
                label="Thời gian giao dịch",
                value="79 giờ",
                turn=0,
                failed=False,
            ),
        ),
        ticket_facts=(),
        rule_candidates=rule_candidates,
        coverage=CoverageCheck(
            app_id="452", expected_skill="withdraw", loaded_skills=("withdraw",), mismatch=False
        ),
        turn_deltas=(),
        drift_changed=False,
        phases=(),
    )


def _narration(**overrides) -> Narration:
    defaults = dict(
        ket_luan="Giao dịch đã treo 79 giờ nên chuyển bộ phận chăm sóc khách hàng.",
        can_cu=CanCu(
            nguon=_CANDIDATE.anchor,
            case_id="C1",
            case_title="Giao dịch đang xử lý",
            file_label="sub-skill-C",
            skill="withdraw",
            trich_dan="Nếu đã quá 3 ngày: Chuyển bộ phận CSKH",
            trich_dan_dong=0,
        ),
        bang_chung=(
            BangChungItem(
                buoc="tool:calculate_time_difference__withdraw",
                nhan="Thời gian giao dịch",
                ket_qua="79 giờ",
            ),
        ),
        do_tin_cay="cao",
    )
    defaults.update(overrides)
    return Narration(**defaults)


def test_valid_narration_passes():
    assert validator.validate(_narration(), _dossier(), "Nếu đã quá 3 ngày: Chuyển bộ phận CSKH")


# V1 -- can_cu.nguon must point at a real candidate anchor in the dossier.
def test_v1_hallucinated_anchor_rejected():
    bad = _narration(can_cu=CanCu(
        nguon="withdraw/references/sub-skill-C.md#L999",
        case_id="C1", case_title="Giao dịch đang xử lý", file_label="sub-skill-C", skill="withdraw",
        trich_dan="Nếu đã quá 3 ngày: Chuyển bộ phận CSKH", trich_dan_dong=0,
    ))
    assert not validator.validate(bad, _dossier(), "Nếu đã quá 3 ngày: Chuyển bộ phận CSKH")


# V2 -- trich_dan must equal the mechanically-extracted quoted_line exactly.
def test_v2_quote_mismatch_rejected():
    narration = _narration()
    assert not validator.validate(narration, _dossier(), "Một dòng hoàn toàn khác")


def test_v2_valid_quote_matching_extraction_passes():
    narration = _narration()
    assert validator.validate(narration, _dossier(), narration.can_cu.trich_dan)


# V3 -- every bang_chung.buoc must be a real tool_evidence step_key.
def test_v3_fabricated_evidence_step_rejected():
    bad = _narration(
        bang_chung=(
            BangChungItem(buoc="tool:made_up_tool", nhan="X", ket_qua="Y"),
        )
    )
    assert not validator.validate(bad, _dossier(), bad.can_cu.trich_dan)


def test_v3_real_evidence_step_passes():
    narration = _narration()
    assert validator.validate(narration, _dossier(), narration.can_cu.trich_dan)


# V4 -- no run of >=6 digits (identifier leak) in ket_luan.
def test_v4_long_digit_run_rejected():
    bad = _narration(ket_luan="Mã giao dịch 123456789 đã treo nên chuyển CSKH.")
    assert not validator.validate(bad, _dossier(), bad.can_cu.trich_dan)


def test_v4_short_digit_runs_allowed():
    narration = _narration(ket_luan="Giao dịch đã treo 79 giờ nên chuyển bộ phận CSKH.")
    assert validator.validate(narration, _dossier(), narration.can_cu.trich_dan)


# V5 -- forbidden technical words must never leak into ket_luan.
@pytest.mark.parametrize("word", ["guardrail", "rule", "trace", "skill", "escalate"])
def test_v5_forbidden_word_rejected(word):
    bad = _narration(ket_luan=f"Hệ thống {word} đã chuyển ticket cho CSKH.")
    assert not validator.validate(bad, _dossier(), bad.can_cu.trich_dan)


def test_v5_clean_conclusion_passes():
    narration = _narration()
    assert validator.validate(narration, _dossier(), narration.can_cu.trich_dan)


# V6 -- ket_luan must not be empty after strip.
def test_v6_empty_conclusion_rejected():
    bad = _narration(ket_luan="   ")
    assert not validator.validate(bad, _dossier(), bad.can_cu.trich_dan)


# V7 -- the mandatory fabricated-number case: "79 giờ" claimed, evidence says
# 43 giờ -- must be rejected. This is the most dangerous 31B failure mode.
def test_v7_fabricated_number_rejected():
    dossier = _dossier(
        tool_evidence=(
            ToolEvidence(
                step_key="tool:calculate_time_difference__withdraw",
                label="Thời gian giao dịch",
                value="43 giờ",
                turn=0,
                failed=False,
            ),
        )
    )
    bad = _narration(ket_luan="Giao dịch đã treo 79 giờ nên chuyển bộ phận CSKH.")
    assert not validator.validate(bad, dossier, bad.can_cu.trich_dan)


def test_v7_number_backed_by_quoted_line_passes():
    # "3 ngày" appears only in the quoted rule line, not in tool_evidence --
    # V7 must accept numbers backed by either source.
    narration = _narration(
        ket_luan="Giao dịch đã quá 3 ngày nên chuyển bộ phận chăm sóc khách hàng.",
    )
    assert validator.validate(narration, _dossier(), narration.can_cu.trich_dan)


def test_v7_number_in_words_is_not_blocked():
    # Spec: numbers spelled out in words are accepted as a known limitation.
    narration = _narration(ket_luan="Giao dịch đã treo ba ngày nên chuyển bộ phận CSKH.")
    assert validator.validate(narration, _dossier(), narration.can_cu.trich_dan)


def test_narration_without_can_cu_still_validates():
    narration = Narration(
        ket_luan="Chưa xác định được kịch bản cụ thể.",
        can_cu=None,
        bang_chung=(),
        do_tin_cay="thap",
    )
    assert validator.validate(narration, _dossier(), None)
