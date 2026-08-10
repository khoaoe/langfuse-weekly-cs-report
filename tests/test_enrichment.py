from __future__ import annotations

from weekly_cs_report.enrichment import (
    ENRICHMENT_NAMES,
    TraceEnrichment,
    apply_trace_enrichment,
    build_trace_enrichment,
    transfer_trigger_for_trace,
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
            "tool:get_transaction_processing_engine_data": [
                {
                    "traceId": "trace-1",
                    "output": {
                        "result": {
                            "transstatus": "-365",
                            "stepresult": "-1013",
                        }
                    },
                },
                {
                    "traceId": "trace-2",
                    "output": {"result": {"transstatus": -383}},
                },
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
        tpe_signals=(("-365", "-1013"),),
    )
    assert enrichment["trace-2"].skills == ("topup",)
    assert enrichment["trace-2"].guardrail_rules == ()
    assert enrichment["trace-2"].tpe_signals == (("-383", None),)


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
            "second": TraceEnrichment(
                intents=("refund_request",),
                skills=("withdraw",),
                guardrail_rules=("off_topic",),
                tpe_signals=(("-365", "-1006"), ("-365", None)),
            ),
        },
    )

    assert enriched.intent is None
    assert enriched.skill is None
    assert enriched.guardrail_rule is None
    assert enriched.tpe_signals == (("-365", "-1006"), ("-365", None))
    assert rules == ("max_replies_exceeded", "off_topic")
    # `skill` collapsing to None must not also erase the fact that two
    # distinct skills actually ran.
    assert enriched.skill_count == 2
    assert enriched.skill_set == ("topup", "withdraw")


def test_multi_skill_trace_is_not_collapsed_to_none():
    """A ticket where three skills ran and a ticket with no `execute` at all
    both used to produce `skill=None` — indistinguishable downstream. The
    count and combination now survive so segments can tell them apart."""
    dimensions = TicketDimensions(
        issue_category="Không xác định", app="Không xác định", app_code=None,
        product_code="Không xác định", entry_point="Không xác định",
        payment_channel="Không xác định", tpe_code=None, tpe_status_raw=None,
        tpe_status_canonical=None, tpe_step=None, tpe_case=None, skill=None,
        intent=None, guardrail_rule=None, escalation_guard_blocked=False,
    )
    traces = (
        TraceRecord("only", "ticket-1", datetime(2026, 7, 1, tzinfo=timezone.utc), 0, {}, {}, "default"),
    )

    multi_skill, _ = apply_trace_enrichment(
        dimensions,
        traces,
        {
            "only": TraceEnrichment(
                skills=("interbank-fund-transfer", "topup", "withdraw"),
            ),
        },
    )
    assert multi_skill.skill is None
    assert multi_skill.skill_count == 3
    assert multi_skill.skill_set == ("interbank-fund-transfer", "topup", "withdraw")

    zero_skill, _ = apply_trace_enrichment(dimensions, traces, {})
    assert zero_skill.skill is None
    assert zero_skill.skill_count == 0
    assert zero_skill.skill_set == ()

    single_skill, _ = apply_trace_enrichment(
        dimensions,
        traces,
        {"only": TraceEnrichment(skills=("topup",))},
    )
    assert single_skill.skill == "topup"
    assert single_skill.skill_count == 1
    assert single_skill.skill_set == ("topup",)


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


def test_blocked_guardrails_preserve_source_stage_and_skill_for_transfer_diagnosis():
    """A source/stage collapse would merge two distinct cs_escalation paths."""
    enrichment = build_trace_enrichment(
        {
            "skill_guardrail_checked": [
                {
                    "traceId": "skill-transfer",
                    "startTime": "2026-08-03T01:00:00Z",
                    "input": {
                        "stage": "output",
                        "skill": "customer-service/interbank-fund-transfer",
                    },
                    "output": {"passed": False, "rule": "cs_escalation"},
                }
            ],
            "output_guardrail": [
                {
                    "traceId": "response-transfer",
                    "startTime": "2026-08-03T02:00:00Z",
                    "output": {"blocked": True, "rule": "cs_escalation"},
                },
                {
                    "traceId": "compliant",
                    "output": {"blocked": False, "rule": "output_compliant"},
                },
            ],
        },
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    assert "output_guardrail" in ENRICHMENT_NAMES
    assert [
        (event.rule, event.source, event.stage, event.skill)
        for event in enrichment["skill-transfer"].guardrail_events
    ] == [
        (
            "cs_escalation",
            "skill_guardrail_checked",
            "output",
            "interbank-fund-transfer",
        )
    ]
    assert [
        (event.rule, event.source, event.stage, event.skill)
        for event in enrichment["response-transfer"].guardrail_events
    ] == [("cs_escalation", "output_guardrail", None, None)]
    assert "compliant" not in enrichment


def test_live_guardrail_aliases_map_to_stable_transfer_reason_codes():
    raw_to_reason = {
        "off_topic_llm": "out_of_scope",
        "empty_input": "empty_message",
        "prompt_injection": "prompt_injection",
        "system_prompt_leak": "prompt_injection",
        "tone_check_error": "output_check_error",
    }
    observations = [
        {
            "traceId": f"trace-{index}",
            "output": {"blocked": True, "rule": rule},
        }
        for index, rule in enumerate(raw_to_reason)
    ]

    enrichment = build_trace_enrichment(
        {"output_guardrail": observations},
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    assert {
        observation["output"]["rule"]: transfer_trigger_for_trace(
            observation["traceId"], enrichment
        ).reason
        for observation in observations
    } == raw_to_reason


def test_same_trace_transfer_trigger_follows_pipeline_stage_precedence():
    """One trace can carry several blocked checks; the first pipeline stage wins."""
    enrichment = build_trace_enrichment(
        {
            "input_guardrail": [
                {
                    "traceId": "transfer-trace",
                    "startTime": "2026-08-03T04:00:00Z",
                    "output": {
                        "blocked": True,
                        "rule": "missing_transaction_id",
                    },
                }
            ],
            "skill_guardrail_checked": [
                {
                    "traceId": "transfer-trace",
                    "startTime": "2026-08-03T02:00:00Z",
                    "input": {
                        "stage": "input",
                        "skill": "customer-service/topup",
                    },
                    "output": {"passed": False, "rule": "off_topic"},
                },
                {
                    "traceId": "transfer-trace",
                    "startTime": "2026-08-03T01:00:00Z",
                    "input": {
                        "stage": "output",
                        "skill": "customer-service/topup",
                    },
                    "output": {"passed": False, "rule": "cs_escalation"},
                },
            ],
            "output_guardrail": [
                {
                    "traceId": "transfer-trace",
                    "startTime": "2026-08-03T00:00:00Z",
                    "output": {"blocked": True, "rule": "cs_escalation"},
                }
            ],
        },
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    trigger = transfer_trigger_for_trace("transfer-trace", enrichment)

    assert trigger is not None
    assert (trigger.reason, trigger.rule, trigger.source, trigger.stage) == (
        "missing_transaction_id",
        "missing_transaction_id",
        "input_guardrail",
        None,
    )


def test_tpe_observations_accept_only_safe_ascii_integer_scalars():
    valid = [
        {
            "traceId": "trace-1",
            "output": {
                "result": {
                    "transstatus": -365,
                    "stepresult": -1013,
                }
            },
        },
        {
            "traceId": "trace-1",
            "output": {
                "result": {
                    "transstatus": "-365",
                    "stepresult": "-1006",
                }
            },
        },
        {
            "traceId": "trace-2",
            "output": {"result": {"transstatus": "20"}},
        },
    ]
    invalid = [
        {
            "traceId": "trace-invalid",
            "output": {
                "result": {
                    "transstatus": candidate,
                    "stepresult": "-1013",
                }
            },
        }
        for candidate in (
            True,
            -365.0,
            "-365|-1013|description",
            "1234567",
            "-٣٦٥",
            " -365 ",
            "-365\n",
        )
    ]
    invalid_steps = [
        {
            "traceId": f"trace-step-{index}",
            "output": {
                "result": {
                    "transstatus": "-365",
                    "stepresult": candidate,
                }
            },
        }
        for index, candidate in enumerate(
            (
                False,
                -1013.0,
                "-1013|description",
                "-1234567",
                "-١٠١٣",
                " -1013 ",
                "-1013\n",
            )
        )
    ]

    enrichment = build_trace_enrichment(
        {
            "tool:get_transaction_processing_engine_data": [
                *valid,
                *invalid,
                *invalid_steps,
            ]
        },
        load_taxonomy(TAXONOMY_V2_PATH),
    )

    assert enrichment["trace-1"].tpe_signals == (
        ("-365", "-1013"),
        ("-365", "-1006"),
    )
    assert enrichment["trace-2"].tpe_signals == (("20", None),)
    assert "trace-invalid" not in enrichment
    assert all(
        enrichment[f"trace-step-{index}"].tpe_signals == (("-365", None),)
        for index in range(len(invalid_steps))
    )
    assert "tool:get_transaction_processing_engine_data" in ENRICHMENT_NAMES
