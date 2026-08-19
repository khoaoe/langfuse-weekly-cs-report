"""Allowlisted JSON runtime events for the protected dashboard service."""

from __future__ import annotations

import json
import logging
import math
import sys
from typing import TextIO


_LOG = logging.getLogger("weekly_cs_report.runtime")
_LOG.setLevel(logging.INFO)
_HANDLER_MARKER = "_weekly_cs_report_json_handler"

_EVENT_FIELDS = {
    "service_start": frozenset(),
    "service_stop": frozenset(),
    "snapshot_load_ignored": frozenset({"code"}),
    "enrichment_incomplete": frozenset({"failed_lanes", "observation_count"}),
    "refresh_start": frozenset({"has_snapshot"}),
    "refresh_success": frozenset(
        {
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
    ),
    "refresh_failure": frozenset({"code"}),
    "refresh_cancelled": frozenset({"code"}),
    "ab_test_background_refresh_success": frozenset(),
    "ab_test_background_refresh_failure": frozenset(),
}
_FIXED_CODES = {
    "snapshot_load_ignored": frozenset(
        {"invalid_snapshot", "incomplete_enrichment"}
    ),
    "refresh_failure": frozenset(
        {"langfuse_unavailable", "data_validation_failed", "refresh_failed"}
    ),
    "refresh_cancelled": frozenset({"cancelled"}),
}
_BOOLEAN_FIELDS = frozenset({"has_snapshot"})
_STRING_FIELDS = frozenset({"failed_lanes"})
_INTEGER_FIELDS = frozenset(
    {"duration_ms", "schema_version", "ticket_count", "trace_count", "observation_count"}
)
_NUMBER_FIELDS = frozenset(
    {
        "coverage_issue_category",
        "coverage_app",
        "coverage_tpe",
        "coverage_intent",
        "coverage_skill",
    }
)


def configure_json_logging(*, stream: TextIO | None = None) -> None:
    """Install the idempotent JSON-only handler owned by runtime events."""

    if any(getattr(handler, _HANDLER_MARKER, False) for handler in _LOG.handlers):
        _LOG.propagate = False
        return
    handler = logging.StreamHandler(sys.stderr if stream is None else stream)
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOG.addHandler(handler)
    _LOG.propagate = False


def emit_event(event: str, **fields: object) -> None:
    """Write one privacy-safe JSON object after strict event validation."""

    allowed_fields = _EVENT_FIELDS.get(event)
    if allowed_fields is None:
        raise ValueError("unsupported runtime event")
    if not set(fields).issubset(allowed_fields):
        raise ValueError("unsupported runtime event field")
    _validate_fields(event, fields)
    _LOG.info(json.dumps({"event": event, **fields}, separators=(",", ":"), sort_keys=True))


def _validate_fields(event: str, fields: dict[str, object]) -> None:
    fixed_codes = _FIXED_CODES.get(event)
    if fixed_codes is not None:
        code = fields.get("code")
        if not isinstance(code, str) or code not in fixed_codes:
            raise ValueError("unsupported runtime event code")
    for name, value in fields.items():
        if name in _STRING_FIELDS:
            if not isinstance(value, str) or not value:
                raise ValueError("runtime event field must be a non-empty string")
        elif name in _BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise ValueError("runtime event field must be boolean")
        elif name in _INTEGER_FIELDS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("runtime event field must be a non-negative integer")
        elif name in _NUMBER_FIELDS:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("runtime event field must be a finite non-negative number")
