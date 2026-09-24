from __future__ import annotations

"""Strict private cache for analyzed Langfuse sessions, keyed by cohort week.

Refreshing the dashboard refetched all twelve reporting weeks from Langfuse
every cycle (~2,767 pages, ~15 minutes) even though almost none of it changes
between two refreshes. This stores the `SessionMetrics` every ticket in the
window analyzed to, so a refresh only fetches what arrived since the last one.

What is stored is the analyzed projection, never the raw traces it came from:
`SessionMetrics` holds classified scalars and mapped taxonomy values, which is
the same grain already persisted in `dashboard_snapshot.json`. The architectural
rule that raw trace/observation payloads never reach disk is unaffected.

Valid sessions alone are not enough to reproduce a full refresh. The cache also
keeps what the analysis set aside -- keyed and unkeyed quality issues -- and,
for every session it saw, the timestamps of its first and last trace. Without
them a cached refresh loses those sessions from the gate and data_quality,
and books the later turn of an excluded session as a brand-new ticket.

Structure mirrors the Freshdesk job caches; the hardened private-file I/O and
validation helpers come from `cache_store` rather than being reimplemented.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path

from .cache_store import (
    atomic_private_json,
    read_private_json,
    validate_monday,
    validate_utc_timestamp,
)
from .models import (
    QualityIssue,
    SessionMetrics,
    TicketDimensions,
    TransferTrigger,
)


_CACHE_SCHEMA_VERSION = 3
_CACHE_KEYS = frozenset({
    "schema_version",
    "fingerprint",
    "fetched_at",
    "built_at",
    "weeks",
    "seen",
    "invalid_keyed",
    "unkeyed",
})
_ISSUE_KEYS = frozenset({"reason", "session_id", "trace_id", "timestamp"})
_PACKAGE_DIRECTORY = Path(__file__).resolve().parent


class SessionCacheError(RuntimeError):
    """A sanitized private-cache contract error."""


@dataclass(frozen=True)
class SessionCache:
    """Everything a refresh needs to skip refetching the weeks it settled.

    ``fetched_at`` is how far the data reaches: every trace up to it was seen.
    ``built_at`` is when the last full refresh ran; incremental refreshes carry
    it forward, so it says how long the cache has gone without being rebuilt.
    ``seen`` maps each session id to its first and last trace timestamps.
    """

    fingerprint: str
    fetched_at: datetime
    built_at: datetime
    weeks: Mapping[date, tuple[SessionMetrics, ...]]
    seen: Mapping[str, tuple[datetime, datetime]]
    invalid_keyed: tuple[QualityIssue, ...]
    unkeyed: tuple[QualityIssue, ...]


def cache_fingerprint(taxonomy_path: Path) -> str:
    """Hash of everything that decides what a session analyzes to.

    Stored sessions carry classified outcomes and mapped dimensions, so a
    change to the taxonomy or to any analysis code must not reuse them.
    ponytail: hashes the whole package, so a web-only deploy also costs one
    full refresh; narrow the file list if deploys get frequent.
    """
    digest = hashlib.sha256(Path(taxonomy_path).read_bytes())
    for source in sorted(_PACKAGE_DIRECTORY.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


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


def _issue_dict(value: QualityIssue) -> dict[str, object]:
    return {
        "reason": value.reason,
        "session_id": value.session_id,
        "trace_id": value.trace_id,
        "timestamp": None if value.timestamp is None else _utc_iso(value.timestamp),
    }


def _issue_from(value: object) -> QualityIssue:
    if not isinstance(value, dict) or set(value) != _ISSUE_KEYS:
        raise SessionCacheError("quality issue is invalid")
    return QualityIssue(
        reason=_require(value["reason"], "issue reason", str),
        session_id=_optional(value["session_id"], "issue session id", str),
        trace_id=_optional(value["trace_id"], "issue trace id", str),
        timestamp=(
            None
            if value["timestamp"] is None
            else _parse_utc(value["timestamp"], "issue timestamp")
        ),
    )


def _issues_from(value: object) -> tuple[QualityIssue, ...]:
    if not isinstance(value, list):
        raise SessionCacheError("session cache is invalid")
    return tuple(_issue_from(item) for item in value)


def load_session_cache(path: Path) -> SessionCache | None:
    """Read the cache, or None when there is none or it predates this format.

    Whether it may be reused is the caller's call (see `cache_fingerprint`):
    this only guarantees the file is well formed.
    """
    value = read_private_json(Path(path), SessionCacheError, "session cache is invalid")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SessionCacheError("session cache is invalid")
    if value.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None
    if set(value) != _CACHE_KEYS:
        raise SessionCacheError("session cache is invalid")
    fingerprint = _require(value["fingerprint"], "fingerprint", str)
    fetched_at = _parse_utc(value["fetched_at"], "fetched timestamp")
    built_at = _parse_utc(value["built_at"], "built timestamp")

    weeks_raw = value["weeks"]
    if not isinstance(weeks_raw, dict):
        raise SessionCacheError("session cache is invalid")
    weeks: dict[date, tuple[SessionMetrics, ...]] = {}
    identifiers: list[str] = []
    for week, sessions_raw in weeks_raw.items():
        validate_monday(week, "cached week", SessionCacheError)
        if not isinstance(sessions_raw, list):
            raise SessionCacheError("session cache is invalid")
        sessions = tuple(_session_from(item) for item in sessions_raw)
        week_date = date.fromisoformat(week)
        if any(session.cohort_week != week_date for session in sessions):
            raise SessionCacheError("session cache is invalid")
        identifiers.extend(session.session_id for session in sessions)
        weeks[week_date] = sessions
    if len(identifiers) != len(set(identifiers)):
        raise SessionCacheError("session cache contains duplicate sessions")

    seen_raw = value["seen"]
    if not isinstance(seen_raw, dict):
        raise SessionCacheError("session cache is invalid")
    seen: dict[str, tuple[datetime, datetime]] = {}
    for session_id, span in seen_raw.items():
        if not isinstance(span, list) or len(span) != 2:
            raise SessionCacheError("session cache is invalid")
        first = _parse_utc(span[0], "first trace timestamp")
        last = _parse_utc(span[1], "last trace timestamp")
        if last < first:
            raise SessionCacheError("session cache is invalid")
        seen[session_id] = (first, last)

    return SessionCache(
        fingerprint=fingerprint,  # type: ignore[arg-type]
        fetched_at=fetched_at,
        built_at=built_at,
        weeks=weeks,
        seen=seen,
        invalid_keyed=_issues_from(value["invalid_keyed"]),
        unkeyed=_issues_from(value["unkeyed"]),
    )


def write_session_cache(path: Path, cache: SessionCache) -> None:
    """Replace the cache with `cache`, atomically and `0600`."""
    payload_weeks: dict[str, object] = {}
    for week, sessions in sorted(cache.weeks.items()):
        if not isinstance(week, date) or week.weekday() != 0:
            raise SessionCacheError("cached week is invalid")
        ordered = sorted(sessions, key=lambda item: item.session_id)
        if any(session.cohort_week != week for session in ordered):
            raise SessionCacheError("cached week is invalid")
        payload_weeks[week.isoformat()] = [_session_dict(s) for s in ordered]
    atomic_private_json(
        Path(path),
        {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "fingerprint": cache.fingerprint,
            "fetched_at": _utc_iso(cache.fetched_at),
            "built_at": _utc_iso(cache.built_at),
            "weeks": payload_weeks,
            "seen": {
                session_id: [_utc_iso(first), _utc_iso(last)]
                for session_id, (first, last) in sorted(cache.seen.items())
            },
            "invalid_keyed": [_issue_dict(i) for i in cache.invalid_keyed],
            "unkeyed": [_issue_dict(i) for i in cache.unkeyed],
        },
        SessionCacheError,
        "session cache is invalid",
    )
