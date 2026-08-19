from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from weekly_cs_report import escalation_dossier as ed
from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.explain_context import load_explain_config
from weekly_cs_report.langfuse_client import LangfuseClient
from weekly_cs_report.skill_rules import parse_snapshot

ROOT = Path(__file__).parents[1]
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "trace_explain"
TAXONOMY = load_taxonomy(ROOT / "config" / "taxonomy.v2.json")
CONFIG = load_explain_config(ROOT / "config" / "explain_context.v1.json")
RULES = parse_snapshot(ROOT / "skills-snapshot")


def _page(data: list[dict]) -> dict:
    return {"data": data, "meta": {"page": 1, "limit": 100, "totalItems": len(data), "totalPages": 1}}


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _client_for_fixture(fixture: dict) -> LangfuseClient:
    traces_by_session: dict[str, list[dict]] = {}
    observations_by_trace: dict[str, list[dict]] = {}
    for entry in fixture.get("traces", []):
        trace = entry["trace"]
        traces_by_session.setdefault(trace["sessionId"], []).append(trace)
        observations_by_trace[trace["id"]] = entry["observations"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/public/traces":
            session_id = request.url.params["sessionId"]
            return httpx.Response(200, json=_page(traces_by_session.get(session_id, [])), request=request)
        trace_id = request.url.params["traceId"]
        return httpx.Response(200, json=_page(observations_by_trace.get(trace_id, [])), request=request)

    return LangfuseClient(
        "https://langfuse.example.test", "pk-test", "sk-test",
        transport=httpx.MockTransport(handler),
    )


def _dossier(fixture_name: str) -> ed.EscalationDossier:
    fixture = _load_fixture(fixture_name)
    client = _client_for_fixture(fixture)
    dossier = ed.build_dossier(client, fixture["ticket_id"], TAXONOMY, CONFIG, RULES)
    assert dossier is not None
    return dossier


def test_e1_skill_guardrail_output_cs_escalation():
    dossier = _dossier("escalation_e1_skill_guardrail_cs_escalation")
    assert dossier.escalation_class == "E1"
    assert dossier.escalated_turn == 0
    assert dossier.blocking_rule == "cs_escalation"
    assert "3 ngay" in dossier.guardrail_reason or "3 ngày" in dossier.guardrail_reason
    assert dossier.skills_loaded == ("withdraw",)
    assert dossier.sub_skills_read == ("sub-skill-C.md",)

    tool_labels = {ev.label: ev.value for ev in dossier.tool_evidence}
    assert tool_labels["Thời gian giao dịch"] == "79 giờ"
    assert tool_labels["Ngân hàng"] == "Vietcombank"
    # load_skill_reference / list_skill_references are navigation, not business evidence.
    assert "Đọc kịch bản" not in tool_labels
    assert "Xem danh mục kịch bản" not in tool_labels

    case_ids = {c.case_id for c in dossier.rule_candidates}
    assert "C1" in case_ids


def test_e1_interbank_fund_transfer_skill_name_resolves_via_snapshot_alias():
    # Ticket 7090152 (real production): the running agent's runtime skill
    # name is "interbank-fund-transfer", but its doc source folder --
    # ../docs/cs-agent-skills/ibft -- and skills-snapshot/ibft/ keep the short
    # alias. Before the fix, rules.get("interbank-fund-transfer", ()) always
    # came back empty, so rule_candidates was always [] for this skill.
    dossier = _dossier("escalation_e1_ibft_skill_name_alias")
    assert dossier.escalation_class == "E1"
    assert dossier.skills_loaded == ("interbank-fund-transfer",)
    assert dossier.sub_skills_read == ("sub-skill-CD.md",)

    case_ids = {c.case_id for c in dossier.rule_candidates}
    assert "D1, D2" in case_ids or {"D1", "D2"} & case_ids


def test_e2_output_guardrail_cs_escalation_family():
    dossier = _dossier("escalation_e2_output_guardrail_cs_escalation_family")
    assert dossier.escalation_class == "E2"
    assert dossier.escalated_turn == 0
    assert dossier.guardrail_reason == "Cau tra loi chua cum chuyen bo phan CSKH"


def test_e3_input_guardrail_blocked_no_case():
    dossier = _dossier("escalation_e3_input_guardrail_blocked")
    assert dossier.escalation_class == "E3"
    assert dossier.guardrail_reason == "Cau hoi nam ngoai pham vi ho tro cua tro ly tu dong"
    assert dossier.blocking_rule == "off_topic_llm"
    assert dossier.rule_candidates == ()
    assert dossier.skills_loaded == ()
    # E3 has no drafted answer to show -- the customer's own message is what
    # the input-stage guardrail actually inspected instead.
    assert dossier.blocked_input_message == "Cho hoi phi chuyen tien quoc te la bao nhieu"
    assert dossier.blocked_response_draft is None


def test_e8_output_content_check_failed_shows_the_blocked_draft():
    # skill_guardrail_checked stage=output blocked on customer_insult -- a
    # real content problem with the bot's OWN drafted answer, unrelated to
    # escalation intent. Must not fall into E3 (that template would falsely
    # say "the customer's question was out of scope").
    dossier = _dossier("escalation_e8_output_content_check_failed")
    assert dossier.escalation_class == "E8"
    assert dossier.blocking_rule == "customer_insult"
    assert dossier.blocked_input_message is None
    assert dossier.blocked_response_draft is not None
    assert "Ban tu doc huong dan di" in dossier.blocked_response_draft
    # mask_free_text must have redacted the 15-digit transaction id.
    assert "260813002120041" not in dossier.blocked_response_draft
    assert "*" in dossier.blocked_response_draft


def test_e9_tone_check_error_is_an_infra_fault_not_bad_content():
    # tone_check_error fires from ToneLlmModule's `except Exception` branch in
    # cs-agent-master -- the guardrail LLM crashed, it never actually judged
    # the draft. Must be its own branch so it is never counted as "bot wrote
    # a bad response" alongside real content failures (E8).
    dossier = _dossier("escalation_e9_tone_check_error")
    assert dossier.escalation_class == "E9"
    assert dossier.blocking_rule == "tone_check_error"
    # The draft still existed (the checker crashed, the draft did not) --
    # showing it lets a PO see there was nothing actually wrong with it.
    assert dossier.blocked_response_draft is not None
    assert "260813002120041" not in dossier.blocked_response_draft


def test_e3_skill_guardrail_blocked_at_input_stage_is_not_e6():
    # Real production data: skill_guardrail_checked blocking at stage=input
    # (missing_transaction_id, off_topic, ...) is one of the most common
    # escalation causes -- it must not fall through to the E6 catch-all.
    dossier = _dossier("escalation_e3_skill_guardrail_input_missing_transaction_id")
    assert dossier.escalation_class == "E3"
    assert dossier.blocking_rule == "missing_transaction_id"


def test_e4_history_guard_points_back_to_turn_zero():
    dossier = _dossier("escalation_e4_history_guard_points_back")
    # The real reason lives in turn 0 (E1-shaped), not the blocked turn 1.
    assert dossier.escalation_class == "E1"
    assert dossier.escalated_turn == 0
    assert dossier.sub_skills_read == ("sub-skill-C.md",)


def test_e5_idempotency_blocked_is_not_an_escalation():
    dossier = _dossier("escalation_e5_idempotency_blocked")
    assert dossier.escalation_class == "E5"
    assert dossier.rule_candidates == ()


def test_e6_no_skill_loaded():
    dossier = _dossier("escalation_e6_no_skill_loaded")
    assert dossier.escalation_class == "E6"
    assert dossier.skills_loaded == ()
    assert dossier.coverage.mismatch is True


def test_e7_tool_instructs_escalate():
    dossier = _dossier("escalation_e7_tool_instructs_escalate")
    assert dossier.escalation_class == "E7"
    assert "cs" in dossier.guardrail_reason.lower()
    tool_message_candidates = [c for c in dossier.rule_candidates if c.source == "tool_message"]
    assert len(tool_message_candidates) == 1
    assert "cs" in tool_message_candidates[0].body.lower()


def test_no_trace_returns_none():
    fixture = {"ticket_id": "0000000", "traces": []}
    client = _client_for_fixture(fixture)
    assert ed.build_dossier(client, "0000000", TAXONOMY, CONFIG, RULES) is None


# --------------------------------------------------------------------------
# rank_candidates
# --------------------------------------------------------------------------


def _candidate(i, source="sub_skill", body="noi dung mac dinh"):
    from weekly_cs_report.skill_rules import RuleCandidate

    return RuleCandidate(
        anchor=f"skill/references/sub-skill-X.md#L{i}",
        skill="withdraw",
        file_label="sub-skill-X",
        case_id=f"X{i}",
        case_title=f"Case {i}",
        body=body,
        source=source,
    )


def test_rank_candidates_caps_at_limit_and_orders_by_score(caplog):
    candidates = [_candidate(i) for i in range(12)]
    # Make one candidate obviously top-scored via a tool mention + known value.
    candidates[5] = _candidate(5, body="goi calculate_time_difference thay gia tri 79 gio roi chuyen cskh")

    with caplog.at_level("WARNING"):
        ranked = ed.rank_candidates(
            candidates,
            tools_called=["calculate_time_difference"],
            known_values=["79 gio"],
            limit=8,
        )

    assert len(ranked) == 8
    assert ranked[0].case_id == "X5"
    assert any("dropping" in message for message in caplog.messages)


def test_rank_candidates_skill_md_scores_lowest():
    sub_skill = _candidate(0, source="sub_skill")
    skill_md = _candidate(1, source="skill_md")
    ranked = ed.rank_candidates([skill_md, sub_skill], limit=8)
    assert ranked[0] is sub_skill
    assert ranked[1] is skill_md


# --------------------------------------------------------------------------
# Contract: dossier never carries raw identifiers (spec 13.2 / CLAUDE.md PII gate)
# --------------------------------------------------------------------------

_LONG_DIGIT_RUN = re.compile(r"[0-9]{9,}")

_ALL_FIXTURES = [
    "escalation_e1_skill_guardrail_cs_escalation",
    "escalation_e2_output_guardrail_cs_escalation_family",
    "escalation_e3_input_guardrail_blocked",
    "escalation_e3_skill_guardrail_input_missing_transaction_id",
    "escalation_e4_history_guard_points_back",
    "escalation_e5_idempotency_blocked",
    "escalation_e6_no_skill_loaded",
    "escalation_e7_tool_instructs_escalate",
]


@pytest.mark.parametrize("fixture_name", _ALL_FIXTURES)
def test_dossier_serialization_carries_no_raw_identifiers(fixture_name):
    dossier = _dossier(fixture_name)
    payload = asdict(dossier)
    payload.pop("ticket_id")  # Ticket ID is the one identifier allowed on browser.
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "traceId" not in serialized
    assert "sessionId" not in serialized

    # rule_candidates carries verbatim skill documentation (support hotlines,
    # published limits) by design (spec §3: "code so khớp từng ký tự") -- a
    # long digit run there is expected static content, not a customer leak.
    # Only the customer-data-bearing fields are scanned for accidental PII.
    customer_facing = {
        "guardrail_reason": payload["guardrail_reason"],
        "ticket_facts": payload["ticket_facts"],
        "tool_evidence": payload["tool_evidence"],
    }
    customer_serialized = json.dumps(customer_facing, ensure_ascii=False)
    assert not _LONG_DIGIT_RUN.search(customer_serialized), customer_serialized


def test_presence_policy_fields_never_carry_a_value():
    dossier = _dossier("escalation_e1_skill_guardrail_cs_escalation")
    for fact in dossier.ticket_facts:
        if fact.label in CONFIG.field_policy_presence:
            assert fact.value is None


def test_narrator_never_receives_raw_observation_shapes():
    # escalation_narrator (Tầng 2) only ever takes EscalationDossier + RuleCandidate
    # shortlist -- this locks the contract before that module exists (spec 7.4).
    import inspect

    from weekly_cs_report import escalation_dossier as module

    source = inspect.getsource(module)
    assert "sessionId" not in source
    assert "traceId" not in source
