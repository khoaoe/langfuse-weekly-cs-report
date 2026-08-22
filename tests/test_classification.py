from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tests.fixtures.traces import TRANSFER_HTML, TRANSFER_PLAIN_SOURCE, TRANSFER_TEXT, trace
from weekly_cs_report.classification import (
    classify_session,
    is_substantive_ai_response,
    is_transfer_response,
    normalize_trace,
)
from weekly_cs_report.cohort import build_cohort_window
from weekly_cs_report.models import QualityIssue, TraceRecord

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
WINDOW = build_cohort_window(datetime(2026, 7, 29, 12, tzinfo=TZ), weeks=12, include_wtd=True)
TURN0 = "2026-07-20T02:00:00Z"
OBSERVED_TRANSFER_TEXT = (
    "Xin lỗi vì sự bất tiện. Yêu cầu của bạn đã được chuyển đến bộ phận phụ "
    "trách để kiểm tra và xử lý. Vui lòng chờ trong giây lát, Zalopay sẽ phản "
    "hồi bạn trong thời gian sớm nhất."
)


def normalized(*raw_traces: dict) -> list[TraceRecord]:
    records = [normalize_trace(item) for item in raw_traces]
    assert all(isinstance(item, TraceRecord) for item in records)
    return records  # type: ignore[return-value]


def classified(*raw_traces: dict):
    return classify_session(normalized(*raw_traces), WINDOW, TRANSFER_TEXT)


def test_transfer_match_requires_the_complete_normalized_response():
    assert is_transfer_response({"response": TRANSFER_HTML}, TRANSFER_TEXT)
    assert is_transfer_response({"response": TRANSFER_PLAIN_SOURCE}, TRANSFER_TEXT)
    assert not is_transfer_response({"response": TRANSFER_TEXT + " thêm"}, TRANSFER_TEXT)
    assert not is_transfer_response(
        {"response": "Giao dịch đang xử lý", "agents_used": ["customer-service"]},
        TRANSFER_TEXT,
    )


@pytest.mark.parametrize(
    "representation",
    [
        TRANSFER_HTML.replace("Xin", "Ｘin"),
        TRANSFER_HTML.upper(),
        TRANSFER_HTML.replace("Quý", "Qu&yacute;"),
        TRANSFER_HTML.replace("vì sự", "vì\u2003sự"),
    ],
)
def test_transfer_match_normalizes_unicode_case_entities_and_unicode_whitespace(representation: str):
    assert is_transfer_response({"response": representation}, TRANSFER_TEXT)


def test_substantive_ai_response_requires_nonempty_nontransfer_string():
    assert is_substantive_ai_response({"response": "Giao dịch đang xử lý"}, TRANSFER_TEXT)
    assert not is_substantive_ai_response({"response": "  "}, TRANSFER_TEXT)
    assert not is_substantive_ai_response({"response": TRANSFER_HTML}, TRANSFER_TEXT)
    assert not is_substantive_ai_response([], TRANSFER_TEXT)


@pytest.mark.parametrize(
    "output",
    [
        {"response": "Đang xử lý", "blocked": True},
        {"response": "Đang xử lý", "passed": False},
        {"response": "Đang xử lý", "violation": "policy"},
        {"response": "  no_data  "},
        {"response": "EXCEPTION"},
        {"response": "ESCALATE_CS_MESSAGE"},
    ],
)
def test_explicit_blocks_and_exact_technical_markers_are_not_substantive(output: dict[str, object]):
    assert not is_substantive_ai_response(output, TRANSFER_TEXT)


@pytest.mark.parametrize(
    ("response", "agents_used"),
    [
        ("Yêu cầu không vượt qua kiểm tra đầu vào", ["guardrail"]),
        ("Yêu cầu không vượt qua kiểm tra đầu vào", "guardrail"),
        (
            "Yêu cầu đã được nhân viên hỗ trợ tiếp nhận.",
            ["idempotency_guard"],
        ),
    ],
)
def test_guardrail_or_system_only_response_is_not_substantive(
    response: str,
    agents_used: object,
):
    assert not is_substantive_ai_response(
        {
            "response": response,
            "agents_used": agents_used,
        },
        TRANSFER_TEXT,
    )


def test_guardrail_marker_alongside_an_ai_agent_does_not_hide_a_real_ai_reply():
    assert is_substantive_ai_response(
        {
            "response": "Giao dịch đang được kiểm tra",
            "agents_used": ["guardrail", "customer-service"],
        },
        TRANSFER_TEXT,
    )


def test_guardrail_before_later_ai_reply_is_classified_from_later_trace():
    guardrail = trace(
        "t0",
        "session-1",
        0,
        TURN0,
        "ESCALATE_CS_MESSAGE",
    )
    guardrail["output"]["agents_used"] = ["guardrail"]

    result = classified(
        guardrail,
        trace("t1", "session-1", 1, "2026-07-20T03:00:00Z", "Giao dịch đang xử lý"),
    )

    assert result.outcome == "ai_end_to_end"
    assert result.ai_first is True
    assert result.no_ai_first_reason is None
    assert result.ai_reply_count == 1
    assert result.reopen_lifetime == 0
    assert result.reopen_within_7d == 0


def test_unclassified_requires_all_traces_to_lack_a_classifiable_outcome():
    first = trace("t0", "session-1", 0, TURN0, "")
    later_guardrail = trace(
        "t1", "session-1", 1, "2026-07-20T03:00:00Z", "ESCALATE_CS_MESSAGE"
    )
    later_guardrail["output"]["agents_used"] = ["guardrail"]

    result = classified(first, later_guardrail)

    assert result.outcome == "unclassified"
    assert result.ai_first is False
    assert result.no_ai_first_reason == "empty_or_technical"
    assert result.ai_reply_count == 0


def test_canonical_transfer_from_a_system_guard_remains_direct_cs():
    transfer = trace("t0", "session-1", 0, TURN0, TRANSFER_HTML)
    transfer["output"]["agents_used"] = ["escalation_history_guard"]

    result = classified(transfer)

    assert result.outcome == "direct_cs"
    assert result.ai_first is False
    assert result.no_ai_first_reason == "direct_cs"
    assert result.ai_reply_count == 0


def test_later_transfer_after_non_classifiable_traces_is_direct_cs():
    result = classified(
        trace("t0", "session-1", 0, TURN0, ""),
        trace("t1", "session-1", 1, "2026-07-20T03:00:00Z", "ESCALATE_CS_MESSAGE"),
        trace("t2", "session-1", 2, "2026-07-20T04:00:00Z", TRANSFER_HTML),
    )

    assert result.outcome == "direct_cs"
    assert result.ai_first is False
    assert result.no_ai_first_reason == "direct_cs"


def test_later_guardrail_only_response_does_not_increment_ai_reply_count():
    guardrail_followup = trace(
        "t1",
        "session-1",
        1,
        "2026-07-21T02:00:00Z",
        "ESCALATE_CS_MESSAGE",
    )
    guardrail_followup["output"]["agents_used"] = ["guardrail"]

    result = classified(
        trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý"),
        guardrail_followup,
    )

    assert result.outcome == "ai_end_to_end"
    assert result.ai_reply_count == 1
    assert result.reopen_lifetime == 1


def test_one_ai_turn0_without_transfer_is_ai_end_to_end():
    result = classified(trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý"))
    assert result.outcome == "ai_end_to_end"
    assert result.ai_first is True
    assert result.ai_reply_count == 1
    assert result.reopen_lifetime == 0
    assert result.reopen_within_7d == 0


def test_later_ai_turns_preserve_ai_end_to_end_and_count_each_reopen():
    result = classified(
        trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý"),
        trace("t1", "session-1", 1, "2026-07-21T02:00:00Z", "Đã kiểm tra giao dịch"),
        trace("t2", "session-1", 2, "2026-07-22T02:00:00Z", "Cần thêm thời gian"),
    )
    assert result.outcome == "ai_end_to_end"
    assert result.ai_reply_count == 3
    assert result.reopen_lifetime == 2


def test_later_transfer_is_ai_then_cs_and_not_an_ai_reply():
    result = classified(
        trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý"),
        trace("t1", "session-1", 1, "2026-07-21T02:00:00Z", TRANSFER_HTML),
    )
    assert result.outcome == "ai_then_cs"
    assert result.ai_first is True
    assert result.ai_reply_count == 1
    assert result.first_transfer_trace_id == "t1"


def test_approved_transfer_variant_is_recognized_before_system_only_filter():
    transfer = trace(
        "t3",
        "session-1",
        3,
        "2026-07-20T05:00:00Z",
        OBSERVED_TRANSFER_TEXT,
    )
    transfer["output"]["agents_used"] = ["escalation_history_guard"]

    result = classify_session(
        normalized(
            trace("t0", "session-1", 0, TURN0, "Đang kiểm tra giao dịch"),
            trace("t1", "session-1", 1, "2026-07-20T03:00:00Z", "Đã kiểm tra"),
            trace("t2", "session-1", 2, "2026-07-20T04:00:00Z", "Cần thêm thời gian"),
            transfer,
        ),
        WINDOW,
        (TRANSFER_TEXT, OBSERVED_TRANSFER_TEXT),
    )

    assert result.outcome == "ai_then_cs"
    assert result.transferred is True
    assert result.ai_reply_count == 3
    assert result.first_transfer_trace_id == "t3"


def test_friday_turn0_counts_weekend_followups_and_later_transfer():
    result = classified(
        trace("t0", "session-1", 0, "2026-07-24T02:00:00Z", "Giao dịch đang xử lý"),
        trace("t1", "session-1", 1, "2026-07-25T02:00:00Z", "Đã kiểm tra giao dịch"),
        trace("t2", "session-1", 2, "2026-07-26T02:00:00Z", TRANSFER_HTML),
    )
    assert result.cohort_status == "complete"
    assert result.outcome == "ai_then_cs"
    assert result.reopen_lifetime == 2
    assert result.ai_reply_count == 2


def test_turn0_transfer_is_direct_cs_without_ai_reply():
    result = classified(trace("t0", "session-1", 0, TURN0, TRANSFER_HTML))
    assert result.outcome == "direct_cs"
    assert result.ai_first is False
    assert result.no_ai_first_reason == "direct_cs"
    assert result.ai_reply_count == 0
    assert result.reopen_lifetime is None
    assert result.reopen_within_7d is None


@pytest.mark.parametrize(
    ("later_timestamp", "expected"),
    [
        ("2026-07-20T03:00:00Z", 1),
        ("2026-07-20T02:00:00Z", 0),
        ("2026-07-27T02:00:00Z", 1),
        ("2026-07-27T02:00:00.000001Z", 0),
    ],
)
def test_reopen_within_7d_uses_an_inclusive_168_hour_boundary(later_timestamp: str, expected: int):
    result = classified(
        trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý"),
        trace("t1", "session-1", 1, later_timestamp, "Đã kiểm tra giao dịch"),
    )
    assert result.reopen_lifetime == 1
    assert result.reopen_within_7d == expected


@pytest.mark.parametrize("weekend_timestamp", ["2026-07-25T02:00:00Z", "2026-07-26T02:00:00Z"])
def test_weekend_canonical_first_is_eligible_with_a_normal_outcome(weekend_timestamp: str):
    result = classified(trace("t0", "session-1", 0, weekend_timestamp, "Giao dịch đang xử lý"))
    assert result.cohort_status == "complete"
    assert result.is_weekend_start is True
    assert result.outcome == "ai_end_to_end"


def test_weekend_immediate_transfer_has_direct_cs_outcome():
    result = classified(trace("t0", "session-1", 0, "2026-07-25T02:00:00Z", TRANSFER_HTML))
    assert result.cohort_status == "complete"
    assert result.outcome == "direct_cs"
    assert result.ai_first is False
    assert result.no_ai_first_reason == "direct_cs"


def test_duplicate_turn_is_a_diagnostic_not_a_quarantine():
    result = classified(
        trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý"),
        trace("t1a", "session-1", 1, "2026-07-21T02:00:00Z", "Đã kiểm tra"),
        trace("t1b", "session-1", 1, "2026-07-21T03:00:00Z", "Đã kiểm tra lại"),
    )
    assert result.outcome == "ai_end_to_end"
    assert result.data_quality == "duplicate_turn"
    assert result.turn_count == 3


@pytest.mark.parametrize(
    "turn, reason",
    [(None, "missing_turn"), ("1", "invalid_turn"), (True, "invalid_turn"), (-1, "invalid_turn")],
)
def test_missing_or_invalid_turn_is_a_normalization_quality_issue(turn: object, reason: str):
    result = normalize_trace(trace("t0", "session-1", turn, TURN0, "Giao dịch đang xử lý"))
    assert isinstance(result, QualityIssue)
    assert result.reason == reason


def test_session_and_freshdesk_mismatch_is_a_quality_issue():
    result = normalize_trace(
        trace(
            "t0",
            "session-1",
            0,
            TURN0,
            "Giao dịch đang xử lý",
            freshdesk_id="ticket-2",
        )
    )
    assert isinstance(result, QualityIssue)
    assert result.reason == "session_freshdesk_mismatch"


def test_normalize_trace_allows_missing_legacy_freshdesk_id():
    raw = trace(
        "trace-1",
        "12345",
        0,
        "2026-07-20T02:00:00Z",
        "AI reply",
    )
    del raw["input"]["other_info"]["freshdesk_id"]

    result = normalize_trace(raw)

    assert isinstance(result, TraceRecord)
    assert result.session_id == "12345"


@pytest.mark.parametrize("freshdesk_id", [None, "", 17])
def test_missing_empty_or_nonstring_freshdesk_id_does_not_create_a_mismatch(freshdesk_id: object):
    raw = trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý")
    raw["input"]["other_info"]["freshdesk_id"] = freshdesk_id
    result = normalize_trace(raw)
    assert isinstance(result, TraceRecord)
    assert result.session_id == "session-1"


def test_malformed_turn0_output_is_unclassified_not_direct_cs():
    result = classified(trace("t0", "session-1", 0, TURN0, {"response": "nested"}))
    assert result.outcome == "unclassified"
    assert result.ai_first is False
    assert result.no_ai_first_reason == "unknown"
    assert result.data_quality == "malformed_output"


@pytest.mark.parametrize("bad_output", [[], {"response": 7}])
def test_malformed_followup_is_quality_warning_but_does_not_hide_a_valid_outcome(
    bad_output: object,
):
    followup = trace("t1", "session-1", 1, "2026-07-21T02:00:00Z", "unused")
    followup["output"] = bad_output
    result = classified(
        trace("t0", "session-1", 0, TURN0, "Giao dịch đang xử lý"),
        followup,
    )
    assert result.outcome == "ai_end_to_end"
    assert result.data_quality == "malformed_output"
    assert result.ai_reply_count == 1


def test_single_trace_starting_at_turn_three_is_not_a_false_reopen():
    result = classified(trace("t1", "session-1", 1, "2026-07-21T02:00:00Z", TRANSFER_HTML))
    assert result.outcome == "direct_cs"
    assert result.data_quality == "no_turn_zero"


def test_single_ai_trace_starting_at_turn_three_is_not_a_false_reopen():
    result = classified(
        trace("t3", "session-1", 3, "2026-07-21T02:00:00Z", "AI reply")
    )
    assert result.outcome == "ai_end_to_end"
    assert result.data_quality == "no_turn_zero"
    assert result.reopen_lifetime == 0
    assert result.reopen_within_7d == 0
