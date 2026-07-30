"""DEPRECATED: the read-only dashboard deployment does not write scores.

This compatibility module remains importable for historical dry-run artifacts;
P1 deliberately does not extend it with dashboard dimensions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Iterable, Iterator

from .cohort import score_anchor_for
from .models import (
    CategoryResult,
    GateStatus,
    ScoreSpec,
    SessionMetrics,
    TransferCategories,
    WeeklySummary,
)

_MAX_EVENTS = 100
_MAX_BYTES = 3_000_000
_NORMAL_OUTCOMES = frozenset(("ai_end_to_end", "ai_then_cs", "direct_cs"))


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_compatible(value: object) -> object:
    if isinstance(value, datetime):
        return _utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_score_id(
    project_id: str,
    analytics_version: str,
    taxonomy_version: str,
    subject_id: str,
    score_name: str,
) -> str:
    identity = (
        f"{project_id}|{analytics_version}|{taxonomy_version}|"
        f"{subject_id}|{score_name}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


def score_to_event(spec: ScoreSpec) -> dict:
    return {
        "id": spec.event_id,
        "type": "score-create",
        "timestamp": _utc_iso(spec.timestamp),
        "body": {
            "id": spec.id,
            "name": spec.name,
            "value": spec.value,
            "dataType": spec.data_type,
            "sessionId": spec.session_id,
            "environment": spec.environment,
            "source": "API",
            "metadata": _json_compatible(spec.metadata),
        },
    }


def _event_id(spec: ScoreSpec) -> str:
    payload = score_to_event(spec)
    del payload["id"]
    payload_hash = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{spec.id}|{payload_hash}"))


def _score(
    *,
    name: str,
    value: str | int | float,
    data_type: str,
    session_id: str,
    timestamp: datetime,
    environment: str,
    metadata: dict[str, object],
    project_id: str,
    analytics_version: str,
    taxonomy_version: str,
) -> ScoreSpec:
    score_id = stable_score_id(
        project_id,
        analytics_version,
        taxonomy_version,
        session_id,
        name,
    )
    incomplete = ScoreSpec(
        id=score_id,
        event_id="",
        name=name,
        value=value,
        data_type=data_type,
        session_id=session_id,
        timestamp=timestamp,
        environment=environment,
        metadata=dict(metadata),
    )
    return replace(incomplete, event_id=_event_id(incomplete))


def _session_metadata(
    metrics: SessionMetrics,
    analytics_version: str,
    taxonomy_version: str,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "analytics_version": analytics_version,
        "taxonomy_version": taxonomy_version,
        "session_id": metrics.session_id,
        "turn0_trace_id": metrics.turn0_trace_id,
        "turn0_timestamp": _utc_iso(metrics.turn0_timestamp),
        "cohort_week": metrics.cohort_week.isoformat(),
        "cohort_status": metrics.cohort_status,
    }
    if metrics.as_of is not None:
        metadata["as_of"] = _utc_iso(metrics.as_of)
    if metrics.first_transfer_trace_id is not None:
        metadata["first_transfer_trace_id"] = metrics.first_transfer_trace_id
        if metrics.outcome in ("direct_cs", "ai_then_cs"):
            metadata["transfer_mode"] = metrics.outcome
    return metadata


def _category_metadata(
    common: dict[str, object],
    category: CategoryResult,
) -> dict[str, object]:
    metadata = dict(common)
    if category.source_fields:
        metadata["source_fields"] = list(category.source_fields)
    if category.value in ("unknown", "multiple") and category.raw_values:
        metadata["raw_values"] = list(category.raw_values)
    return metadata


def build_session_scores(
    metrics: SessionMetrics,
    categories: TransferCategories | None,
    gate_status: GateStatus,
    project_id: str,
    analytics_version: str,
    taxonomy_version: str,
) -> tuple[ScoreSpec, ...]:
    if not gate_status.core_allowed:
        return ()

    common = _session_metadata(metrics, analytics_version, taxonomy_version)
    scores: list[ScoreSpec] = []

    def add(
        name: str,
        value: str | int | float,
        data_type: str,
        metadata: dict[str, object] = common,
    ) -> None:
        scores.append(
            _score(
                name=name,
                value=value,
                data_type=data_type,
                session_id=metrics.session_id,
                timestamp=metrics.score_timestamp,
                environment=metrics.environment,
                metadata=metadata,
                project_id=project_id,
                analytics_version=analytics_version,
                taxonomy_version=taxonomy_version,
            )
        )

    add("ai_first", int(metrics.ai_first), "NUMERIC")
    add("ai_reply_count", metrics.ai_reply_count, "NUMERIC")
    add("ticket_data_quality", metrics.data_quality, "CATEGORICAL")
    if not metrics.ai_first and metrics.no_ai_first_reason is not None:
        add("no_ai_first_reason", metrics.no_ai_first_reason, "CATEGORICAL")
    if metrics.outcome in _NORMAL_OUTCOMES:
        add("ticket_outcome", metrics.outcome, "CATEGORICAL")
    if metrics.ai_first and metrics.reopen_lifetime is not None:
        add("reopen_lifetime", metrics.reopen_lifetime, "NUMERIC")
    if metrics.ai_first and metrics.reopen_within_7d is not None:
        add("reopen_within_7d", metrics.reopen_within_7d, "NUMERIC")

    if metrics.first_transfer_trace_id is None or categories is None:
        return tuple(scores)
    category_families = (
        (
            gate_status.business_allowed,
            "transfer_business_category",
            categories.business,
        ),
        (gate_status.tpe_allowed, "transfer_tpe_group", categories.tpe),
        (
            gate_status.guardrail_allowed,
            "transfer_guardrail_rule",
            categories.guardrail_rule,
        ),
    )
    for allowed, name, category in category_families:
        if allowed:
            add(
                name,
                category.value,
                "CATEGORICAL",
                _category_metadata(common, category),
            )
    return tuple(scores)


def _weekly_metadata(
    summary: WeeklySummary,
    session_id: str,
    analytics_version: str,
    taxonomy_version: str,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "analytics_version": analytics_version,
        "taxonomy_version": taxonomy_version,
        "session_id": session_id,
        "cohort_week": summary.cohort_week.isoformat(),
        "cohort_status": summary.cohort_status,
        "cohort_maturity": (
            "mature"
            if summary.reopen_7d_denominator is not None
            else "immature"
        ),
        "session_count": summary.total_tickets,
    }
    if summary.as_of is not None:
        metadata["as_of"] = _utc_iso(summary.as_of)
    return metadata


def _rate_metadata(
    common: dict[str, object],
    numerator: int,
    denominator: int,
) -> dict[str, object]:
    return {
        **common,
        "numerator": numerator,
        "denominator": denominator,
    }


def build_weekly_scores(
    summary: WeeklySummary,
    gate_status: GateStatus,
    project_id: str,
    analytics_version: str,
    taxonomy_version: str,
) -> tuple[ScoreSpec, ...]:
    if not gate_status.core_allowed:
        return ()

    session_id = f"weekly-cs-summary:{summary.cohort_week.isoformat()}"
    timestamp = score_anchor_for(summary.cohort_week)
    common = _weekly_metadata(
        summary,
        session_id,
        analytics_version,
        taxonomy_version,
    )
    values: tuple[
        tuple[str, int | float | None, dict[str, object]],
        ...,
    ] = (
        ("weekly_cs_total_tickets", summary.total_tickets, common),
        ("weekly_cs_ai_first_count", summary.ai_first_count, common),
        (
            "weekly_cs_ai_first_rate",
            summary.ai_first_rate,
            _rate_metadata(
                common,
                summary.ai_first_count,
                summary.total_tickets,
            ),
        ),
        (
            "weekly_cs_ai_end_to_end_count",
            summary.ai_end_to_end_count,
            common,
        ),
        ("weekly_cs_ai_then_cs_count", summary.ai_then_cs_count, common),
        ("weekly_cs_direct_cs_count", summary.direct_cs_count, common),
        ("weekly_cs_unclassified_count", summary.unclassified_count, common),
        (
            "weekly_cs_reopen_7d_rate",
            summary.reopen_7d_rate,
            (
                _rate_metadata(
                    common,
                    round(
                        summary.reopen_7d_rate
                        * summary.reopen_7d_denominator
                    ),
                    summary.reopen_7d_denominator,
                )
                if summary.reopen_7d_rate is not None
                and summary.reopen_7d_denominator is not None
                else common
            ),
        ),
        (
            "weekly_cs_reopen_7d_denominator",
            summary.reopen_7d_denominator,
            common,
        ),
        (
            "weekly_cs_reopen_lifetime_rate",
            summary.reopen_lifetime_rate,
            (
                _rate_metadata(
                    common,
                    round(
                        summary.reopen_lifetime_rate
                        * summary.ai_first_count
                    ),
                    summary.ai_first_count,
                )
                if summary.reopen_lifetime_rate is not None
                else common
            ),
        ),
        ("weekly_cs_ai_reply_p50", summary.ai_reply_p50, common),
        ("weekly_cs_ai_reply_p90", summary.ai_reply_p90, common),
        ("weekly_cs_ai_reply_max", summary.ai_reply_max, common),
    )
    return tuple(
        _score(
            name=name,
            value=value,
            data_type="NUMERIC",
            session_id=session_id,
            timestamp=timestamp,
            environment="default",
            metadata=metadata,
            project_id=project_id,
            analytics_version=analytics_version,
            taxonomy_version=taxonomy_version,
        )
        for name, value, metadata in values
        if value is not None
    )


def _batch_size(events: list[dict]) -> int:
    return len(_canonical_json({"batch": events}).encode("utf-8"))


def _validate_limit(value: int, maximum: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 1 or value > maximum:
        raise ValueError(f"{field_name} must be between 1 and {maximum}")


def chunk_events(
    events: Iterable[dict],
    max_events: int = _MAX_EVENTS,
    max_bytes: int = _MAX_BYTES,
) -> Iterator[list[dict]]:
    _validate_limit(max_events, _MAX_EVENTS, "max_events")
    _validate_limit(max_bytes, _MAX_BYTES, "max_bytes")

    chunk: list[dict] = []
    for event in events:
        candidate = [*chunk, event]
        if len(candidate) <= max_events and _batch_size(candidate) < max_bytes:
            chunk = candidate
            continue
        if not chunk:
            raise ValueError("single event exceeds max_bytes")
        yield chunk
        chunk = [event]
        if _batch_size(chunk) >= max_bytes:
            raise ValueError("single event exceeds max_bytes")
    if chunk:
        yield chunk
