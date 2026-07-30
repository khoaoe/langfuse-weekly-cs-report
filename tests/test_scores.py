from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from weekly_cs_report.models import (
    CategoryResult,
    GateStatus,
    SessionMetrics,
    TransferCategories,
    WeeklySummary,
)
from weekly_cs_report.scores import (
    build_session_scores,
    build_weekly_scores,
    chunk_events,
    score_to_event,
    stable_score_id,
)

UTC = timezone.utc
VIETNAM = ZoneInfo("Asia/Ho_Chi_Minh")
AS_OF = datetime(2026, 7, 29, 12, tzinfo=VIETNAM)
ALL_ALLOWED = GateStatus(True, True, True, True, ())


def session_metrics(**changes: object) -> SessionMetrics:
    metrics = SessionMetrics(
        session_id="ticket-123",
        turn0_trace_id="trace-0",
        turn0_timestamp=datetime(2026, 7, 20, 2, tzinfo=UTC),
        cohort_week=date(2026, 7, 20),
        score_timestamp=datetime(2026, 7, 20, 5, tzinfo=UTC),
        cohort_status="complete",
        ai_first=True,
        no_ai_first_reason=None,
        outcome="ai_then_cs",
        reopen_lifetime=1,
        reopen_within_7d=1,
        ai_reply_count=2,
        first_transfer_trace_id="trace-1",
        data_quality="valid",
        environment="production",
        as_of=AS_OF,
    )
    return replace(metrics, **changes)


def weekly_summary(**changes: object) -> WeeklySummary:
    summary = WeeklySummary(
        cohort_week=date(2026, 7, 20),
        cohort_status="complete",
        total_tickets=10,
        ai_first_count=7,
        ai_first_rate=0.7,
        ai_end_to_end_count=4,
        ai_then_cs_count=3,
        direct_cs_count=2,
        unclassified_count=1,
        reopen_7d_rate=0.25,
        reopen_7d_denominator=4,
        reopen_lifetime_rate=0.5,
        ai_reply_p50=1,
        ai_reply_p90=4,
        ai_reply_max=7,
        as_of=AS_OF,
    )
    return replace(summary, **changes)


def categories() -> TransferCategories:
    return TransferCategories(
        business=CategoryResult(
            "multiple",
            raw_values=("topup", "withdraw"),
            source_fields=("title", "meta.domain"),
        ),
        tpe=CategoryResult(
            "processor_timeout",
            raw_values=("-374",),
            source_fields=("output.result.tpe_error_code",),
        ),
        guardrail_rule=CategoryResult(
            "unknown",
            raw_values=("unmapped_policy",),
            source_fields=("metadata.rule",),
        ),
    )


def session_scores(
    metrics: SessionMetrics | None = None,
    transfer_categories: TransferCategories | None = None,
    gates: GateStatus = ALL_ALLOWED,
    taxonomy_version: str = "v1",
):
    return build_session_scores(
        metrics or session_metrics(),
        transfer_categories,
        gates,
        project_id="project-1",
        analytics_version="analytics-v1",
        taxonomy_version=taxonomy_version,
    )


def weekly_scores(summary: WeeklySummary | None = None, gates: GateStatus = ALL_ALLOWED):
    return build_weekly_scores(
        summary or weekly_summary(),
        gates,
        project_id="project-1",
        analytics_version="analytics-v1",
        taxonomy_version="v1",
    )


def by_name(scores):
    return {score.name: score for score in scores}


def test_score_body_ids_are_stable_and_versioned():
    first = stable_score_id(
        "project-1", "analytics-v1", "v1", "ticket-123", "ai_first"
    )
    retry = stable_score_id(
        "project-1", "analytics-v1", "v1", "ticket-123", "ai_first"
    )
    new_taxonomy = stable_score_id(
        "project-1", "analytics-v1", "v2", "ticket-123", "ai_first"
    )

    assert first == retry
    assert first != new_taxonomy


def test_event_ids_are_payload_sensitive_while_score_identity_and_anchor_stay_stable():
    original = by_name(session_scores())["ai_reply_count"]
    exact_retry = by_name(session_scores())["ai_reply_count"]
    changed = by_name(
        session_scores(replace(session_metrics(), ai_reply_count=3))
    )["ai_reply_count"]

    assert exact_retry.event_id == original.event_id
    assert changed.event_id != original.event_id
    assert changed.id == original.id
    assert changed.timestamp == original.timestamp


def test_event_id_changes_when_controlled_metadata_changes():
    original = by_name(session_scores())["ai_first"]
    changed = by_name(
        session_scores(
            replace(session_metrics(), as_of=AS_OF + timedelta(minutes=1))
        )
    )["ai_first"]

    assert changed.id == original.id
    assert changed.timestamp == original.timestamp
    assert changed.event_id != original.event_id


def test_score_event_has_exact_ingestion_shape_and_only_session_association():
    score = by_name(session_scores(transfer_categories=categories()))[
        "transfer_business_category"
    ]

    event = score_to_event(score)

    assert event == {
        "id": score.event_id,
        "type": "score-create",
        "timestamp": "2026-07-20T05:00:00Z",
        "body": {
            "id": score.id,
            "name": "transfer_business_category",
            "value": "multiple",
            "dataType": "CATEGORICAL",
            "sessionId": "ticket-123",
            "environment": "production",
            "source": "API",
            "metadata": {
                "analytics_version": "analytics-v1",
                "taxonomy_version": "v1",
                "session_id": "ticket-123",
                "turn0_trace_id": "trace-0",
                "turn0_timestamp": "2026-07-20T02:00:00Z",
                "cohort_week": "2026-07-20",
                "cohort_status": "complete",
                "as_of": "2026-07-29T05:00:00Z",
                "first_transfer_trace_id": "trace-1",
                "transfer_mode": "ai_then_cs",
                "source_fields": ["title", "meta.domain"],
                "raw_values": ["topup", "withdraw"],
            },
        },
    }
    assert not {
        "traceId",
        "observationId",
        "datasetRunId",
    } & event["body"].keys()
    assert not {
        "title",
        "input",
        "output",
        "response",
        "comments",
    } & event["body"]["metadata"].keys()


def test_core_gate_blocks_every_session_and_weekly_score_family():
    category_flags_only = GateStatus(False, True, True, True, ("structural",))

    assert session_scores(transfer_categories=categories(), gates=category_flags_only) == ()
    assert weekly_scores(gates=category_flags_only) == ()


def test_session_core_score_eligibility_uses_only_three_normal_outcomes():
    ai_first_names = tuple(score.name for score in session_scores())
    direct_cs_names = tuple(
        score.name
        for score in session_scores(
            session_metrics(
                ai_first=False,
                no_ai_first_reason="direct_cs",
                outcome="direct_cs",
                reopen_lifetime=None,
                reopen_within_7d=None,
                ai_reply_count=0,
            )
        )
    )
    unclassified_names = tuple(
        score.name
        for score in session_scores(
            session_metrics(
                ai_first=False,
                no_ai_first_reason="empty_or_technical",
                outcome="unclassified",
                reopen_lifetime=None,
                reopen_within_7d=None,
                first_transfer_trace_id=None,
            )
        )
    )

    assert ai_first_names == (
        "ai_first",
        "ai_reply_count",
        "ticket_data_quality",
        "ticket_outcome",
        "reopen_lifetime",
        "reopen_within_7d",
    )
    assert direct_cs_names == (
        "ai_first",
        "ai_reply_count",
        "ticket_data_quality",
        "no_ai_first_reason",
        "ticket_outcome",
    )
    assert unclassified_names == (
        "ai_first",
        "ai_reply_count",
        "ticket_data_quality",
        "no_ai_first_reason",
    )


def test_session_reopen_within_7d_is_omitted_when_not_yet_defined():
    names = {
        score.name
        for score in session_scores(session_metrics(reopen_within_7d=None))
    }

    assert "reopen_lifetime" in names
    assert "reopen_within_7d" not in names


def test_transferred_category_families_follow_their_independent_gates():
    gates = GateStatus(True, False, True, False, ("category_quality",))

    scores = by_name(session_scores(transfer_categories=categories(), gates=gates))

    assert "transfer_business_category" not in scores
    assert scores["transfer_tpe_group"].value == "processor_timeout"
    assert "transfer_guardrail_rule" not in scores
    assert "raw_values" not in scores["transfer_tpe_group"].metadata
    assert scores["transfer_tpe_group"].metadata["source_fields"] == [
        "output.result.tpe_error_code"
    ]


def test_categories_require_both_a_transfer_and_provided_classification():
    without_categories = {
        score.name for score in session_scores(transfer_categories=None)
    }
    without_transfer = {
        score.name
        for score in session_scores(
            session_metrics(first_transfer_trace_id=None),
            transfer_categories=categories(),
        )
    }

    assert not any(name.startswith("transfer_") for name in without_categories)
    assert not any(name.startswith("transfer_") for name in without_transfer)


def test_weekly_scores_use_exact_names_synthetic_session_and_default_environment():
    scores = weekly_scores()

    assert tuple(score.name for score in scores) == (
        "weekly_cs_total_tickets",
        "weekly_cs_ai_first_count",
        "weekly_cs_ai_first_rate",
        "weekly_cs_ai_end_to_end_count",
        "weekly_cs_ai_then_cs_count",
        "weekly_cs_direct_cs_count",
        "weekly_cs_unclassified_count",
        "weekly_cs_reopen_7d_rate",
        "weekly_cs_reopen_7d_denominator",
        "weekly_cs_reopen_lifetime_rate",
        "weekly_cs_ai_reply_p50",
        "weekly_cs_ai_reply_p90",
        "weekly_cs_ai_reply_max",
    )
    assert {score.session_id for score in scores} == {
        "weekly-cs-summary:2026-07-20"
    }
    assert {score.environment for score in scores} == {"default"}
    assert {score.timestamp for score in scores} == {
        datetime(2026, 7, 20, 5, tzinfo=UTC)
    }
    assert {score.data_type for score in scores} == {"NUMERIC"}


def test_weekly_scores_omit_every_undefined_metric_without_sentinels():
    scores = weekly_scores(
        weekly_summary(
            reopen_7d_rate=None,
            reopen_7d_denominator=None,
            reopen_lifetime_rate=None,
            ai_reply_p50=None,
            ai_reply_p90=None,
            ai_reply_max=None,
        )
    )

    assert tuple(score.name for score in scores) == (
        "weekly_cs_total_tickets",
        "weekly_cs_ai_first_count",
        "weekly_cs_ai_first_rate",
        "weekly_cs_ai_end_to_end_count",
        "weekly_cs_ai_then_cs_count",
        "weekly_cs_direct_cs_count",
        "weekly_cs_unclassified_count",
    )


def test_pipeline_models_reject_naive_optional_run_timestamp():
    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        session_metrics(as_of=datetime(2026, 7, 29, 12))
    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        weekly_summary(as_of=datetime(2026, 7, 29, 12))


def test_chunk_events_greedily_respects_the_hard_event_count():
    events = [{"id": f"event-{index}"} for index in range(205)]

    chunks = list(chunk_events(events))

    assert [len(chunk) for chunk in chunks] == [100, 100, 5]
    assert [event for chunk in chunks for event in chunk] == events


def test_chunk_events_keeps_every_canonical_request_strictly_below_byte_limit():
    events = [
        {"id": f"event-{index}", "metadata": {"evidence": "đ" * 900}}
        for index in range(8)
    ]
    original = copy.deepcopy(events)
    limit = 4_000

    chunks = list(chunk_events(events, max_events=100, max_bytes=limit))

    assert len(chunks) > 1
    assert all(
        len(
            json.dumps(
                {"batch": chunk},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        < limit
        for chunk in chunks
    )
    assert events == original


@pytest.mark.parametrize(
    ("max_events", "max_bytes"),
    [(0, 3_000_000), (101, 3_000_000), (100, 0), (100, 3_000_001)],
)
def test_chunk_events_rejects_limits_outside_the_ingestion_contract(
    max_events: int, max_bytes: int
):
    with pytest.raises(ValueError):
        list(chunk_events([], max_events=max_events, max_bytes=max_bytes))


def test_chunk_events_rejects_one_event_that_cannot_fit_strictly_below_limit():
    event = {"metadata": {"evidence": "x" * 100}}

    with pytest.raises(ValueError, match="single event"):
        list(chunk_events([event], max_bytes=50))
