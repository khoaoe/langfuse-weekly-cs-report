from __future__ import annotations

import json
import io
import logging

import pytest

from weekly_cs_report import runtime_logging
from weekly_cs_report.runtime_logging import configure_json_logging, emit_event


def test_events_are_json_objects_with_only_approved_scalar_fields(caplog):
    with caplog.at_level(logging.INFO, logger="weekly_cs_report.runtime"):
        emit_event("service_start")
        emit_event("snapshot_load_ignored", code="invalid_snapshot")
        emit_event("refresh_start", has_snapshot=False)
        emit_event(
            "refresh_success",
            duration_ms=12,
            schema_version=5,
            ticket_count=0,
            trace_count=1,
            observation_count=2,
            coverage_issue_category=0.9,
        )
        emit_event("refresh_failure", code="refresh_failed")
        emit_event("refresh_cancelled", code="cancelled")
        emit_event("service_stop")

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "weekly_cs_report.runtime"
    ]

    assert [event["event"] for event in events] == [
        "service_start",
        "snapshot_load_ignored",
        "refresh_start",
        "refresh_success",
        "refresh_failure",
        "refresh_cancelled",
        "service_stop",
    ]
    assert all(
        set(event) <= {
            "event",
            "code",
            "has_snapshot",
            "duration_ms",
            "schema_version",
            "ticket_count",
            "trace_count",
            "observation_count",
            "coverage_issue_category",
            "coverage_app",
            "coverage_tpe",
            "coverage_intent",
            "coverage_skill",
        }
        for event in events
    )


@pytest.mark.parametrize(
    ("event", "fields"),
    [
        ("unknown", {}),
        ("service_start", {"identity": "operator@example.test"}),
        ("refresh_success", {"ticket_count": ["300"]}),
        ("refresh_failure", {"code": "operator@example.test"}),
    ],
)
def test_events_reject_unapproved_or_non_scalar_context(event, fields):
    with pytest.raises(ValueError):
        emit_event(event, **fields)


@pytest.mark.parametrize(
    ("event", "fields"),
    [
        ("refresh_success", {"coverage_tpe": float("nan")}),
        ("refresh_success", {"coverage_tpe": float("inf")}),
        ("refresh_success", {"coverage_tpe": -0.1}),
        ("refresh_success", {"coverage_tpe": True}),
        ("refresh_success", {"duration_ms": -1}),
        ("refresh_success", {"duration_ms": True}),
        ("refresh_success", {"ticket_count": "1"}),
    ],
)
def test_events_reject_nonfinite_negative_boolean_and_unsupported_scalars(event, fields):
    with pytest.raises(ValueError):
        emit_event(event, **fields)


def test_configure_uses_one_dedicated_unprefixed_json_handler_with_existing_root_handler():
    logger = logging.getLogger("weekly_cs_report.runtime")
    root = logging.getLogger()
    runtime_stream = io.StringIO()
    root_stream = io.StringIO()
    root_handler = logging.StreamHandler(root_stream)
    root_handler.setFormatter(logging.Formatter("PREFIX:%(message)s"))
    previous_handlers = list(logger.handlers)
    previous_propagate = logger.propagate
    logger.handlers.clear()
    root.addHandler(root_handler)
    try:
        configure_json_logging(stream=runtime_stream)
        configure_json_logging(stream=io.StringIO())
        emit_event("service_start")

        assert runtime_stream.getvalue().splitlines() == ['{"event":"service_start"}']
        assert root_stream.getvalue() == ""
        assert logger.propagate is False
        assert len(logger.handlers) == 1
        assert logger.handlers[0].formatter._fmt == "%(message)s"
    finally:
        logger.handlers.clear()
        logger.handlers.extend(previous_handlers)
        logger.propagate = previous_propagate
        root.removeHandler(root_handler)
