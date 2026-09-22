from __future__ import annotations

"""Strict private cache for analyzed Langfuse sessions, keyed by cohort week.

Refreshing the dashboard refetched all twelve reporting weeks from Langfuse
every cycle (~2,767 pages, ~15 minutes) even though a closed week's traces
never change. This stores the `SessionMetrics` a closed week analyzed to, so a
refresh only fetches the weeks that can still move.

What is stored is the analyzed projection, never the raw traces it came from:
`SessionMetrics` holds classified scalars and mapped taxonomy values, which is
the same grain already persisted in `dashboard_snapshot.json`. The architectural
rule that raw trace/observation payloads never reach disk is unaffected.

Structure mirrors the Freshdesk job caches; the hardened private-file I/O and
validation helpers come from `cache_store` rather than being reimplemented.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
import re

from .cache_store import (
    atomic_private_json,
    read_private_json,
    validate_monday,
    validate_utc_timestamp,
)
from .models import (
    SessionMetrics,
    TicketDimensions,
    TransferTrigger,
)


_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = frozenset({"schema_version", "storage_version", "weeks"})
_WEEK_KEYS = frozenset({"fetched_at", "sessions"})
_FILENAME = re.compile(r"session_cache_(\d{4}-\d{2}-\d{2})\.json\Z")


class SessionCacheError(RuntimeError):
    """A sanitized private-cache contract error."""


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, label: str) -> datetime:
    validate_utc_timestamp(value, label, SessionCacheError)
    assert isinstance(value, str)
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _optional(value: object, label: str, kind: type) -> object | None:
    if value is None:
        return None
    if not isinstance(value, kind) or isinstance(value, bool) is (kind is not bool):
        raise SessionCacheError(f"{label} is invalid")
    return value


def _require(value: object, label: str, kind: type) -> object:
    if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool)):
        raise SessionCacheError(f"{label} is invalid")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(i, str) for i in value):
        raise SessionCacheError(f"{label} is invalid")
    return tuple(value)


def _dimensions_dict(value: TicketDimensions) -> dict[str, object]:
    return {
        "issue_category": value.issue_category,
        "app": value.app,
        "app_code": value.app_code,
        "product_code": value.product_code,
        "entry_point": value.entry_point,
        "payment_channel": value.payment_channel,
        "tpe_code": value.tpe_code,
        "tpe_status_raw": value.tpe_status_raw,
        "tpe_status_canonical": value.tpe_status_canonical,
        "tpe_step": value.tpe_step,
        "tpe_case": value.tpe_case,
        "skill": value.skill,
        "intent": value.intent,
        "guardrail_rule": value.guardrail_rule,
        "escalation_guard_blocked": value.escalation_guard_blocked,
        "tpe_signals": [list(pair) for pair in value.tpe_signals],
        "skill_count": value.skill_count,
        "skill_set": list(value.skill_set),
        "tool_error_codes": list(value.tool_error_codes),
        "model_core": value.model_core,
    }


def _dimensions_from(value: object) -> TicketDimensions:
    item = _require(value, "dimensions", dict)
    assert isinstance(item, dict)
    signals_raw = item.get("tpe_signals")
    if not isinstance(signals_raw, list):
        raise SessionCacheError("dimensions is invalid")
    signals: list[tuple[str, str | None]] = []
    for pair in signals_raw:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not (pair[1] is None or isinstance(pair[1], str))
        ):
            raise SessionCacheError("dimensions is invalid")
        signals.append((pair[0], pair[1]))
    try:
        return TicketDimensions(
            issue_category=_require(item["issue_category"], "issue_category", str),
            app=_require(item["app"], "app", str),
            app_code=_optional(item["app_code"], "app_code", int),
            product_code=_require(item["product_code"], "product_code", str),
            entry_point=_require(item["entry_point"], "entry_point", str),
            payment_channel=_require(item["payment_channel"], "payment_channel", str),
            tpe_code=_optional(item["tpe_code"], "tpe_code", str),
            tpe_status_raw=_optional(item["tpe_status_raw"], "tpe_status_raw", str),
            tpe_status_canonical=_optional(
                item["tpe_status_canonical"], "tpe_status_canonical", str
            ),
            tpe_step=_optional(item["tpe_step"], "tpe_step", str),
            tpe_case=_optional(item["tpe_case"], "tpe_case", int),
            skill=_optional(item["skill"], "skill", str),
            intent=_optional(item["intent"], "intent", str),
            guardrail_rule=_optional(item["guardrail_rule"], "guardrail_rule", str),
            escalation_guard_blocked=_require(
                item["escalation_guard_blocked"], "escalation_guard_blocked", bool
            ),
            tpe_signals=tuple(signals),
            skill_count=_require(item["skill_count"], "skill_count", int),
            skill_set=_string_tuple(item["skill_set"], "skill_set"),
            tool_error_codes=_string_tuple(
                item["tool_error_codes"], "tool_error_codes"
            ),
            model_core=_optional(item["model_core"], "model_core", str),
        )
    except KeyError:
        raise SessionCacheError("dimensions is invalid") from None


def _trigger_dict(value: TransferTrigger | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "reason": value.reason,
        "rule": value.rule,
        "source": value.source,
        "stage": value.stage,
        "skill": value.skill,
    }


def _trigger_from(value: object) -> TransferTrigger | None:
    if value is None:
        return None
    item = _require(value, "transfer trigger", dict)
    assert isinstance(item, dict)
    try:
        return TransferTrigger(
            reason=_require(item["reason"], "reason", str),
            rule=_require(item["rule"], "rule", str),
            source=_require(item["source"], "source", str),
            stage=_optional(item["stage"], "stage", str),
            skill=_optional(item["skill"], "skill", str),
        )
    except KeyError:
        raise SessionCacheError("transfer trigger is invalid") from None


def _session_dict(value: SessionMetrics) -> dict[str, object]:
    return {
        "session_id": value.session_id,
        "turn0_trace_id": value.turn0_trace_id,
        "turn0_timestamp": _utc_iso(value.turn0_timestamp),
        "cohort_week": value.cohort_week.isoformat(),
        "score_timestamp": _utc_iso(value.score_timestamp),
        "cohort_status": value.cohort_status,
        "ai_first": value.ai_first,
        "no_ai_first_reason": value.no_ai_first_reason,
        "outcome": value.outcome,
        "reopen_lifetime": value.reopen_lifetime,
        "reopen_within_7d": value.reopen_within_7d,
        "ai_reply_count": value.ai_reply_count,
        "first_transfer_trace_id": value.first_transfer_trace_id,
        "data_quality": value.data_quality,
        "environment": value.environment,
        "as_of": None if value.as_of is None else _utc_iso(value.as_of),
        "is_weekend_start": value.is_weekend_start,
        "turn_count": value.turn_count,
        "transferred": value.transferred,
        "dimensions": _dimensions_dict(value.dimensions),
        "guardrail_rules": list(value.guardrail_rules),
        "transfer_trigger": _trigger_dict(value.transfer_trigger),
        "control_reopen_within_7d": value.control_reopen_within_7d,
        "reopen_offsets_hours": list(value.reopen_offsets_hours),
    }


def _session_from(value: object) -> SessionMetrics:
    item = _require(value, "session", dict)
    assert isinstance(item, dict)
    offsets = item.get("reopen_offsets_hours")
    if not isinstance(offsets, list) or any(
        not isinstance(i, (int, float)) or isinstance(i, bool) for i in offsets
    ):
        raise SessionCacheError("session is invalid")
    try:
        cohort_week = date.fromisoformat(
            _require(item["cohort_week"], "cohort week", str)  # type: ignore[arg-type]
        )
    except (KeyError, ValueError):
        raise SessionCacheError("session is invalid") from None
    try:
        return SessionMetrics(
            session_id=_require(item["session_id"], "session id", str),
            turn0_trace_id=_require(item["turn0_trace_id"], "turn0 trace id", str),
            turn0_timestamp=_parse_utc(item["turn0_timestamp"], "turn0 timestamp"),
            cohort_week=cohort_week,
            score_timestamp=_parse_utc(item["score_timestamp"], "score timestamp"),
            cohort_status=_require(item["cohort_status"], "cohort status", str),
            ai_first=_require(item["ai_first"], "ai first", bool),
            no_ai_first_reason=_optional(
                item["no_ai_first_reason"], "no ai first reason", str
            ),
            outcome=_optional(item["outcome"], "outcome", str),
            reopen_lifetime=_optional(item["reopen_lifetime"], "reopen lifetime", int),
            reopen_within_7d=_optional(
                item["reopen_within_7d"], "reopen within 7d", int
            ),
            ai_reply_count=_require(item["ai_reply_count"], "ai reply count", int),
            first_transfer_trace_id=_optional(
                item["first_transfer_trace_id"], "first transfer trace id", str
            ),
            data_quality=_require(item["data_quality"], "data quality", str),
            environment=_require(item["environment"], "environment", str),
            as_of=(
                None
                if item["as_of"] is None
                else _parse_utc(item["as_of"], "as of")
            ),
            is_weekend_start=_require(
                item["is_weekend_start"], "is weekend start", bool
            ),
            turn_count=_require(item["turn_count"], "turn count", int),
            transferred=_require(item["transferred"], "transferred", bool),
            dimensions=_dimensions_from(item["dimensions"]),
            guardrail_rules=_string_tuple(
                item["guardrail_rules"], "guardrail rules"
            ),
            transfer_trigger=_trigger_from(item["transfer_trigger"]),
            control_reopen_within_7d=_optional(
                item["control_reopen_within_7d"], "control reopen within 7d", int
            ),
            reopen_offsets_hours=tuple(float(i) for i in offsets),
        )
    except KeyError:
        raise SessionCacheError("session is invalid") from None


def load_session_cache(
    path: Path, *, storage_version: int
) -> dict[date, tuple[SessionMetrics, ...]]:
    """Read cached sessions per cohort week, or `{}` when unusable.

    A cache written against a different projection version is discarded rather
    than migrated: the stored sessions feed aggregates whose shape that version
    defines, so reusing them across a bump is how a silent miscount starts.
    """
    value = read_private_json(Path(path), SessionCacheError, "session cache is invalid")
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) != _CACHE_KEYS:
        raise SessionCacheError("session cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION:
        return {}
    if value["storage_version"] != storage_version:
        return {}
    weeks = value["weeks"]
    if not isinstance(weeks, dict):
        raise SessionCacheError("session cache is invalid")

    result: dict[date, tuple[SessionMetrics, ...]] = {}
    for week, payload in weeks.items():
        validate_monday(week, "cached week", SessionCacheError)
        if not isinstance(payload, dict) or set(payload) != _WEEK_KEYS:
            raise SessionCacheError("session cache is invalid")
        validate_utc_timestamp(
            payload["fetched_at"], "fetched timestamp", SessionCacheError
        )
        sessions_raw = payload["sessions"]
        if not isinstance(sessions_raw, list):
            raise SessionCacheError("session cache is invalid")
        sessions = tuple(_session_from(item) for item in sessions_raw)
        week_date = date.fromisoformat(week)
        if any(session.cohort_week != week_date for session in sessions):
            raise SessionCacheError("session cache is invalid")
        identifiers = [session.session_id for session in sessions]
        if len(identifiers) != len(set(identifiers)):
            raise SessionCacheError("session cache contains duplicate sessions")
        result[week_date] = sessions
    return result


def write_session_cache(
    path: Path,
    weeks: Mapping[date, Sequence[SessionMetrics]],
    *,
    storage_version: int,
    fetched_at: datetime,
) -> None:
    """Replace the cache with `weeks`, atomically and `0600`."""
    payload_weeks: dict[str, object] = {}
    for week, sessions in weeks.items():
        if not isinstance(week, date) or week.weekday() != 0:
            raise SessionCacheError("cached week is invalid")
        ordered = sorted(sessions, key=lambda item: item.session_id)
        if any(session.cohort_week != week for session in ordered):
            raise SessionCacheError("cached week is invalid")
        payload_weeks[week.isoformat()] = {
            "fetched_at": _utc_iso(fetched_at),
            "sessions": [_session_dict(session) for session in ordered],
        }
    atomic_private_json(
        Path(path),
        {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "storage_version": storage_version,
            "weeks": payload_weeks,
        },
        SessionCacheError,
        "session cache is invalid",
    )
