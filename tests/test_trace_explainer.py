from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.langfuse_client import LangfuseClient
from weekly_cs_report.trace_explainer import (
    TraceStep,
    build_trace_explanation,
    compact_trace_steps,
    compute_verdict,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "trace_explain"
TAXONOMY_V2_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"
TAXONOMY = load_taxonomy(TAXONOMY_V2_PATH)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _page(data: list[dict]) -> dict:
    return {"data": data, "meta": {"page": 1, "limit": 100, "totalItems": len(data), "totalPages": 1}}


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


def _explanation(fixture_name: str):
    fixture = _load_fixture(fixture_name)
    client = _client_for_fixture(fixture)
    return build_trace_explanation(client, fixture["ticket_id"], TAXONOMY)


# --- Snapshot-style tests over the 4 required fixtures --------------------


def test_normal_reply_answers_and_keeps_visible_steps_in_order():
    explanation = _explanation("normal_reply")

    assert explanation.ticket_id == "5551001"
    assert len(explanation.turns) == 1
    turn = explanation.turns[0]
    assert turn.verdict == "tra_loi"
    assert turn.verdict_reason == "Agent đã trả lời khách"
    assert [step.key for step in turn.steps] == [
        "idempotency_guard",
        "escalation_history_guard",
        "input_guardrail",
        "route",
        "skills_loaded",
        "tool:get_transaction_processing_engine_data",
        "tool:load_skill_reference__withdraw",
        "skill_guardrail_checked",
        "skill_guardrail_checked",
        "output_guardrail",
    ]
    assert all(step.outcome == "ok" for step in turn.steps)
    assert turn.tools_called == [
        "get_transaction_processing_engine_data",
        "load_skill_reference__withdraw",
    ]
    assert turn.skills_used == ["withdraw"]
    assert turn.user_input == "Giao dich rut tien bi treo, chua nhan duoc tien"


def test_input_guardrail_blocked_transfers_to_cs_with_rule_in_reason():
    explanation = _explanation("input_guardrail_blocked")

    turn = explanation.turns[0]
    assert turn.verdict == "chuyen_cs"
    assert turn.verdict_reason == "Câu hỏi vướng rule off_topic"
    steps_by_key = {step.key: step for step in turn.steps}
    assert steps_by_key["input_guardrail"].outcome == "chan"


def test_reopen_session_second_turn_is_blocked_by_escalation_history():
    explanation = _explanation("reopen_escalation_blocked")

    assert len(explanation.turns) == 2
    first, second = explanation.turns
    assert first.verdict == "chuyen_cs"
    # Regression: skill_guardrail_checked signals blocked via output.passed=False,
    # not output.blocked (that key does not exist on this span). See enrichment.py.
    assert first.verdict_reason == "Skill vướng rule cs_escalation"
    assert second.verdict == "khong_tra_loi"
    assert second.verdict_reason == "Ticket đã chuyển CS ở lượt trước"
    assert [step.key for step in second.steps] == [
        "idempotency_guard",
        "escalation_history_guard",
    ]
    assert second.steps[1].outcome == "chan"


def test_multi_turn_ticket_keeps_both_turns_ordered_by_timestamp():
    explanation = _explanation("multi_turn_normal")

    assert len(explanation.turns) == 2
    assert explanation.turns[0].turn == 0
    assert explanation.turns[1].turn == 1
    assert explanation.turns[0].timestamp < explanation.turns[1].timestamp
    assert all(turn.verdict == "tra_loi" for turn in explanation.turns)


def test_build_trace_explanation_returns_none_when_session_has_no_traces():
    client = _client_for_fixture({"traces": []})
    assert build_trace_explanation(client, "9999999", TAXONOMY) is None


def test_langfuse_url_reuses_ticket_explorer_filter_format():
    explanation = _explanation("normal_reply")
    parsed = urlparse(explanation.langfuse_url)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces"
    )
    query = parse_qs(parsed.query)
    assert query["filter"] == ["sessionId;stringOptions;;any of;5551001"]
    start_text, end_text = query["dateRange"][0].split("-")
    assert int(start_text) < int(end_text)


# --- Isolated compact()/verdict() tests (spec section 9 "Test riêng") -----


def test_unknown_span_is_shown_with_its_raw_name_not_dropped():
    observations = [
        {
            "id": "x1",
            "name": "some_future_span",
            "startTime": "2026-01-01T00:00:00Z",
            "input": {"a": 1},
            "output": {"b": 2},
        },
    ]

    steps = compact_trace_steps(observations, TAXONOMY)

    assert len(steps) == 1
    assert steps[0].key == "some_future_span"
    assert steps[0].label == "some_future_span"
    assert steps[0].outcome == "ok"


def test_llm_call_iterations_are_always_hidden():
    observations = [
        {"id": "x1", "name": "llm_call:iter_0", "startTime": "2026-01-01T00:00:00Z", "input": {"messages_count": 3}, "output": {"text": "hi"}},
        {"id": "x2", "name": "llm_call:iter_7", "startTime": "2026-01-01T00:00:01Z", "input": {}, "output": {}},
    ]

    assert compact_trace_steps(observations, TAXONOMY) == []


def test_tool_call_order_survives_hidden_llm_call_spans_between_them():
    observations = [
        {"id": "a", "name": "tool:get_bank_info", "startTime": "2026-01-01T00:00:01Z", "input": {}, "output": {}},
        {"id": "b", "name": "llm_call:iter_0", "startTime": "2026-01-01T00:00:02Z", "input": {}, "output": {}},
        {"id": "c", "name": "tool:get_bank_name", "startTime": "2026-01-01T00:00:03Z", "input": {}, "output": {}},
    ]

    steps = compact_trace_steps(observations, TAXONOMY)

    assert [step.key for step in steps] == ["tool:get_bank_info", "tool:get_bank_name"]


def test_evidence_strips_noisy_keys_and_truncates_long_strings():
    long_value = "x" * 3000
    observations = [
        {
            "id": "a",
            "name": "tool:custom_lookup",
            "startTime": "2026-01-01T00:00:00Z",
            "input": {"messages_count": 5, "trans_id": "123"},
            "output": {
                "iteration": 2,
                "stop_reason": "stop",
                "usageDetails": {"input": 10},
                "result": long_value,
            },
        },
    ]

    steps = compact_trace_steps(observations, TAXONOMY)
    evidence = steps[0].evidence

    assert "messages_count" not in evidence["input"]
    assert evidence["input"]["trans_id"] == "123"
    assert "iteration" not in evidence["output"]
    assert "stop_reason" not in evidence["output"]
    assert "usageDetails" not in evidence["output"]
    assert len(evidence["output"]["result"]) == 2000


def test_skill_guardrail_checked_reads_passed_field_not_blocked():
    """Real observations never carry output.blocked for this span, only
    output.passed (verified against config/taxonomy.v2.json and a live
    session fetch). A literal output.blocked check would never fire."""
    observations = [
        {
            "id": "a",
            "name": "skill_guardrail_checked",
            "startTime": "2026-01-01T00:00:00Z",
            "input": {"skill": "customer-service/withdraw", "stage": "output"},
            "output": {"passed": False, "rule": "cs_escalation"},
        },
    ]

    steps = compact_trace_steps(observations, TAXONOMY)

    assert steps[0].outcome == "chan"


def test_compute_verdict_priority_favours_idempotency_over_later_guards():
    steps = [
        TraceStep(key="idempotency_guard", label="x", outcome="chan", summary="s", evidence={}),
        TraceStep(key="input_guardrail", label="x", outcome="chan", summary="s", evidence={"output": {"rule": "off_topic"}}),
    ]

    verdict, reason = compute_verdict(steps)

    assert verdict == "khong_tra_loi"
    assert reason == "Ticket đã được xử lý trước đó"


def test_compute_verdict_defaults_to_tra_loi_when_nothing_blocked():
    steps = [
        TraceStep(key="idempotency_guard", label="x", outcome="ok", summary="s", evidence={}),
    ]

    assert compute_verdict(steps) == ("tra_loi", "Agent đã trả lời khách")
