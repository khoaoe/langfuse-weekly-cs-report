from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from weekly_cs_report.models import SessionMetrics, TicketDimensions, TraceRecord
from weekly_cs_report.reopen_population import (
    MISSING_REQUIRED_TEXT,
    ReopenSession,
    build_reopen_population,
)


UTC = ZoneInfo("UTC")


def _dimensions(issue_category: str = "Thanh toán-IBFT") -> TicketDimensions:
    return TicketDimensions(
        issue_category=issue_category,
        app="ZaloPay",
        app_code=1,
        product_code="IBFT",
        entry_point="ticket",
        payment_channel="bank",
        tpe_code=None,
        tpe_status_raw=None,
        tpe_status_canonical=None,
        tpe_step=None,
        tpe_case=None,
        skill="ibft",
        intent="transfer",
        guardrail_rule=None,
        escalation_guard_blocked=False,
    )


def _metrics(
    session_id: str,
    *,
    ai_first: bool = True,
    outcome: str = "ai_end_to_end",
    reopen_within_7d: int | None = 1,
    data_quality: str = "valid",
    control_reopen_within_7d: int | None = None,
    weekend: bool = False,
    domain: str = "Thanh toán-IBFT",
) -> SessionMetrics:
    timestamp = datetime(2026, 7, 25 if weekend else 20, 2, tzinfo=UTC)
    return SessionMetrics(
        session_id=session_id,
        turn0_trace_id=f"{session_id}-metric-anchor",
        turn0_timestamp=timestamp,
        cohort_week=date(2026, 7, 20),
        score_timestamp=datetime(2026, 7, 27, 17, tzinfo=UTC),
        cohort_status="complete",
        ai_first=ai_first,
        no_ai_first_reason=None if ai_first else "direct_cs",
        outcome=outcome,
        reopen_lifetime=1 if ai_first else None,
        reopen_within_7d=reopen_within_7d,
        ai_reply_count=1 if ai_first else 0,
        first_transfer_trace_id=None,
        data_quality=data_quality,
        environment="default",
        is_weekend_start=weekend,
        turn_count=2,
        transferred=outcome in {"ai_then_cs", "direct_cs"},
        dimensions=_dimensions(domain),
        control_reopen_within_7d=control_reopen_within_7d,
    )


def _trace(
    session_id: str,
    trace_id: str,
    turn: int,
    timestamp: str,
    *,
    user_input: object,
    response: object,
    meta: dict[str, object] | None = None,
    decoys: bool = False,
) -> TraceRecord:
    input_data: dict[str, object] = {
        "user_input": user_input,
        "other_info": {
            "meta": meta or {},
        },
    }
    if decoys:
        input_data["title"] = "DECoy title"
        input_data["comments"] = ["DECoy comment"]
        input_data["other_info"] = {
            "meta": meta or {},
            "title": "DECoy nested title",
            "comments": ["DECoy nested comment"],
        }
    return TraceRecord(
        id=trace_id,
        session_id=session_id,
        timestamp=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        turn=turn,
        input_data=input_data,
        output_data={"response": response, "extra": "DECoy output"},
        environment="default",
    )


def _valid_traces(session_id: str) -> tuple[TraceRecord, ...]:
    return (
        _trace(
            session_id,
            f"{session_id}-first",
            3,
            "2026-07-20T02:00:00Z",
            user_input="Câu hỏi ban đầu",
            response="Câu trả lời AI",
        ),
        _trace(
            session_id,
            f"{session_id}-followup",
            8,
            "2026-07-21T02:00:00Z",
            user_input="Câu hỏi quay lại",
            response="Câu trả lời sau",
        ),
    )


def test_builds_eligible_population_from_canonical_first_and_keeps_weekend():
    weekday = _metrics("weekday", domain="Thanh toán-IBFT")
    weekend = _metrics(
        "weekend",
        weekend=True,
        domain="Tài khoản",
        outcome="ai_then_cs",
    )
    shuffled_weekend = (
        _trace(
            "weekend",
            "later-by-turn",
            9,
            "2026-07-27T02:00:00Z",
            user_input="Theo dõi cuối tuần",
            response="later",
        ),
        _trace(
            "weekend",
            "canonical-first",
            4,
            "2026-07-25T02:00:00Z",
            user_input="Mở ticket cuối tuần",
            response="AI cuối tuần",
        ),
    )

    result = build_reopen_population(
        [weekday, weekend],
        {
            "weekday": _valid_traces("weekday"),
            "weekend": shuffled_weekend,
        },
    )

    assert tuple(item.session_id for item in result.sessions) == ("weekday", "weekend")
    assert result.sessions[1].anchor_trace_id == "canonical-first"
    assert result.sessions[1].followup_trace_id == "later-by-turn"
    assert result.sessions[1].week == date(2026, 7, 20)
    assert result.sessions[1].domain == "Tài khoản"
    assert result.sessions[1].outcome == "ai_then_cs"
    assert "skipped_weekend_start" not in result.excluded_counts


@pytest.mark.parametrize(
    ("changes", "session_id"),
    [
        ({"ai_first": False}, "not-ai-first"),
        ({"reopen_within_7d": 0}, "not-reopened"),
        ({"outcome": "direct_cs"}, "direct"),
        ({"outcome": "unclassified"}, "unclassified"),
        ({"data_quality": "duplicate_turn"}, "invalid-quality"),
    ],
)
def test_requires_all_four_population_eligibility_conditions(changes, session_id):
    metrics = replace(_metrics(session_id), **changes)

    result = build_reopen_population(
        [metrics],
        {session_id: _valid_traces(session_id)},
    )

    assert result.sessions == ()


def test_deduplicates_each_session_for_population_and_control():
    ai = _metrics("ai")
    direct_reopened = _metrics(
        "direct",
        ai_first=False,
        outcome="direct_cs",
        reopen_within_7d=None,
        control_reopen_within_7d=1,
    )

    result = build_reopen_population(
        [ai, ai, direct_reopened, direct_reopened],
        {"ai": _valid_traces("ai")},
    )

    assert tuple(item.session_id for item in result.sessions) == ("ai",)
    assert result.control.numerator == 1
    assert result.control.denominator == 1
    assert result.control.rate == 1.0


def test_uses_first_positive_followup_in_canonical_order_within_168_hours():
    traces = (
        _trace(
            "ordered",
            "same-turn-later-id",
            7,
            "2026-07-21T02:00:00Z",
            user_input="followup chosen",
            response="later",
        ),
        _trace(
            "ordered",
            "negative-delta",
            5,
            "2026-07-19T02:00:00Z",
            user_input="must skip",
            response="earlier clock",
        ),
        _trace(
            "ordered",
            "canonical-first",
            3,
            "2026-07-20T02:00:00Z",
            user_input="initial",
            response="answer",
        ),
        _trace(
            "ordered",
            "after-boundary",
            6,
            "2026-07-27T02:00:00.000001Z",
            user_input="must also skip",
            response="too late",
        ),
    )

    result = build_reopen_population(
        [_metrics("ordered")],
        {"ordered": traces},
    )

    assert result.sessions[0].followup_trace_id == "same-turn-later-id"
    assert result.sessions[0].followup_user_text == "followup chosen"


def test_reads_only_three_exact_text_paths_and_masks_meta_from_every_trace():
    traces = (
        _trace(
            "pii",
            "first",
            3,
            "2026-07-20T02:00:00Z",
            user_input="Ban đầu app-secret và 0901234567",
            response="AI trả lời transaction-secret",
            meta={"UserID": "app-secret"},
            decoys=True,
        ),
        _trace(
            "pii",
            "followup",
            8,
            "2026-07-21T02:00:00Z",
            user_input="Quay lại app-secret transaction-secret",
            response="ignored response",
            meta={
                "TransID": "transaction-secret",
                "Số điện thoại người dùng": "0901234567",
            },
            decoys=True,
        ),
    )

    result = build_reopen_population(
        [_metrics("pii", domain="Domain from SessionMetrics")],
        {"pii": traces},
    )

    item = result.sessions[0]
    assert item.initial_user_text == "Ban đầu [PII] và [PII]"
    assert item.initial_ai_text == "AI trả lời [PII]"
    assert item.followup_user_text == "Quay lại [PII] [PII]"
    assert item.domain == "Domain from SessionMetrics"
    rendered = repr(item)
    assert "app-secret" not in rendered
    assert "transaction-secret" not in rendered
    assert "DECoy" not in rendered


def test_missing_exact_text_is_excluded_with_fixed_code_and_no_raw_log(caplog):
    secret = "raw secret must never be logged"
    traces = (
        _trace(
            "missing",
            "first",
            3,
            "2026-07-20T02:00:00Z",
            user_input=secret,
            response=None,
            decoys=True,
        ),
        _trace(
            "missing",
            "followup",
            8,
            "2026-07-21T02:00:00Z",
            user_input="followup",
            response="ignored",
        ),
    )

    result = build_reopen_population(
        [_metrics("missing")],
        {"missing": traces},
    )

    assert result.sessions == ()
    assert result.excluded_counts == {MISSING_REQUIRED_TEXT: 1}
    assert secret not in caplog.text


def test_reopen_session_contains_no_raw_objects_and_hides_all_text_from_repr():
    item = ReopenSession(
        session_id="session",
        anchor_trace_id="first",
        followup_trace_id="followup",
        week=date(2026, 7, 20),
        domain="IBFT",
        outcome="ai_end_to_end",
        initial_user_text="secret initial",
        initial_ai_text="secret response",
        followup_user_text="secret followup",
    )

    assert vars(item).keys() == {
        "session_id",
        "anchor_trace_id",
        "followup_trace_id",
        "week",
        "domain",
        "outcome",
        "initial_user_text",
        "initial_ai_text",
        "followup_user_text",
    }
    assert "secret" not in repr(item)


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "gọi lại 0901234567",
        "mail person@example.com",
        "xem https://example.com/private",
        "thẻ 4111 1111 1111 1111",
    ),
)
def test_reopen_session_rejects_unmasked_deterministic_pii_before_any_llm_boundary(
    unsafe_text,
):
    with pytest.raises(ValueError, match="reopen session text is not masked"):
        ReopenSession(
            session_id="unsafe",
            anchor_trace_id="first",
            followup_trace_id="followup",
            week=date(2026, 7, 20),
            domain="IBFT",
            outcome="ai_end_to_end",
            initial_user_text=unsafe_text,
            initial_ai_text="masked answer",
            followup_user_text="masked followup",
        )
