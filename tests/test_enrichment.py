from __future__ import annotations

from weekly_cs_report.enrichment import (
    ENRICHMENT_NAMES,
    TraceEnrichment,
    apply_trace_enrichment,
    build_trace_enrichment,
)
from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.models import TicketDimensions, TraceRecord
from datetime import datetime, timezone
from pathlib import Path


TAXONOMY_V2_PATH = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


def test_bulk_observations_keep_all_distinct_valid_values_for_fail_closed_reduction():
    enrichment = build_trace_enrichment(
        {
            "route": [
                {"traceId": "trace-1", "startTime": "2026-07-01T02:00:00Z", "timestamp": "2000-01-01T00:00:00Z", "id": "later", "metadata": {"intent": "refund_request"}},
                {"traceId": "trace-1", "startTime": "2026-07-01T01:00:00Z", "id": "first", "metadata": {"intent": "refund_issue"}},
            ],
            "execute": [
                {"traceId": "trace-1", "timestamp": "2026-07-01T01:00:00Z", "id": "first", "metadata": {"skills_used": ["customer-service/topup", "customer-service/interbank-fund-transfer"]}},
                {"traceId": "trace-2", "metadata": {"skills_used": "customer-service/topup"}},
            ],
            "input_guardrail": [
                {"traceId": "trace-1", "timestamp": "2026-07-01T02:00:00Z", "id": "later", "output": {"rule": "missing_transaction_id"}},
            ],
            "skill_guardrail_checked": [
                {"traceId": "trace-1", "timestamp": "2026-07-01T01:00:00Z", "id": "first", "output": {"rule": "off_topic"}},
                {"traceId": "trace-2", "output": {"rule": "input_compliant"}},
            ],
            "escalation_history_guard": [
                {"traceId": "trace-1", "output": {"blocked": True}},
            ],
        },
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    assert set(enrichment) == {"trace-1", "trace-2"}
    assert enrichment["trace-1"] == TraceEnrichment(
        intents=("refund_issue", "refund_request"),
        skills=("interbank-fund-transfer", "topup"),
        guardrail_rules=("missing_transaction_id", "off_topic"),
        escalation_guard_blocked=True,
    )
    assert enrichment["trace-2"].skills == ("topup",)
    assert enrichment["trace-2"].guardrail_rules == ()


def test_conflicting_scalars_fail_closed_but_max_replies_remains_observable_internally():
    dimensions = TicketDimensions(
        issue_category="Không xác định", app="Không xác định", app_code=None,
        product_code="Không xác định", entry_point="Không xác định",
        payment_channel="Không xác định", tpe_code=None, tpe_status_raw=None,
        tpe_status_canonical=None, tpe_step=None, tpe_case=None, skill=None,
        intent=None, guardrail_rule=None, escalation_guard_blocked=False,
    )
    traces = (
        TraceRecord("first", "ticket-1", datetime(2026, 7, 1, tzinfo=timezone.utc), 0, {}, {}, "default"),
        TraceRecord("second", "ticket-1", datetime(2026, 7, 1, 1, tzinfo=timezone.utc), 1, {}, {}, "default"),
    )

    enriched, rules = apply_trace_enrichment(
        dimensions,
        traces,
        {
            "first": TraceEnrichment(intents=("payment_issue",), skills=("topup",), guardrail_rules=("max_replies_exceeded",)),
            "second": TraceEnrichment(intents=("refund_request",), skills=("withdraw",), guardrail_rules=("off_topic",)),
        },
    )

    assert enriched.intent is None
    assert enriched.skill is None
    assert enriched.guardrail_rule is None
    assert rules == ("max_replies_exceeded", "off_topic")


def test_execute_skill_rejects_pii_like_values():
    enrichment = build_trace_enrichment(
        {
            "execute": [
                {"traceId": "trace-1", "metadata": {"skills_used": ["0901234567", "550e8400-e29b-41d4-a716-446655440000", "123456789", "customer-service/topup"]}},
            ],
        },
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    assert enrichment["trace-1"].skills == ("topup",)


def test_unrecognized_or_malformed_observations_do_not_create_trace_enrichment():
    enrichment = build_trace_enrichment(
        {name: [{"traceId": "trace-1", "output": {"rule": "customer free text"}}] for name in ENRICHMENT_NAMES},
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    assert enrichment == {}
