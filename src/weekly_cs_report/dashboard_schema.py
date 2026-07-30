from __future__ import annotations

"""The deliberately small, privacy-safe v4 browser/storage projection.

Raw Langfuse traces never cross this boundary.  This module is also the one
place that defines the persisted browser contract, so a schema change cannot
accidentally grow an unreviewed JSON surface.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import re
from typing import Mapping
from unicodedata import category, decimal, normalize

from .models import AnalysisResult, SessionMetrics, WeeklySummary
from .reopen_shadow import ReopenReasonShadow, unavailable_shadow
from .report import ReportRun


_STORAGE_VERSION = 4
_TICKET_ID_PATTERN = re.compile(r"[1-9][0-9]{0,19}\Z")
_PHONE = re.compile(r"(?:^|\D)(?:0|84|\+84)[0-9]{8,10}(?:$|\D)")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_INTENT_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
_TPE_CODE_PATTERN = re.compile(r"^-?[0-9]{1,6}$")
_GUARDRAIL_RULES = frozenset(
    {
        "cs_escalation",
        "empty_message_marker",
        "max_replies_exceeded",
        "missing_transaction_id",
        "prompt_injection_llm",
        "off_topic",
    }
)
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_URL = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_VIETNAMESE_FAMILY_NAMES = frozenset({
    "nguyễn", "nguyen", "trần", "tran", "lê", "le", "phạm", "pham", "hoàng", "hoang", "huỳnh", "huynh", "vũ", "vu", "võ", "vo", "đặng", "dang", "bùi", "bui", "đỗ", "do", "hồ", "ho", "ngô", "ngo", "dương", "duong", "lý", "ly",
})
_VIETNAMESE_NAME_MIDDLES = frozenset({"văn", "van", "thị", "thi"})
_OUTCOMES = ("ai_end_to_end", "ai_then_cs", "direct_cs", "unclassified")
_VIEWS = ("mon_sun", "mon_fri")
_SEGMENTS = (
    "issue_category",
    "app",
    "product_code",
    "skill",
    "intent",
    "tpe",
    "guardrail_rule",
    "entry_point",
)
_MISSING = "Không xác định"
_QUALITY_LABELS = frozenset(
    {
        "valid", "empty_or_technical", "malformed_output", "invalid_timestamp",
        "missing_trace_id", "missing_session_id", "missing_turn", "invalid_turn",
        "session_freshdesk_mismatch", "empty_session", "session_id_mismatch",
        "duplicate_turn", "missing_turn0", "no_turn_zero", "unknown_quality_issue",
    }
)
_DASHBOARD_KEYS = frozenset(
    {
        "generated_at", "source", "enrichment_status", "data_range", "views",
        "coverage", "unmapped_tpe_codes", "gate_status", "data_quality",
    }
)
_TICKET_KEYS = frozenset(
    {
        "ticket_id", "cohort_week", "cohort_status", "is_weekend_start", "outcome",
        "ai_first", "transferred", "reopen_lifetime", "reopen_within_7d",
        "ai_reply_count", "turn_count", "gt4_turn", "issue_category", "app",
        "product_code", "skill", "intent", "tpe_code", "tpe_status",
        "guardrail_rule", "escalation_guard_blocked", "data_quality",
    }
)
_WEEKLY_KEYS = frozenset(
    {
        "cohort_week", "cohort_status", "week_definition", "has_data",
        "total_tickets", "ai_first_count", "ai_first_rate", "ai_end_to_end_count",
        "ai_then_cs_count", "direct_cs_count", "unclassified_count", "reopen_7d_rate",
        "reopen_7d_denominator", "reopen_lifetime_rate", "reopen_lifetime_numerator",
        "reopen_lifetime_denominator", "ai_reply_mean_ai_first", "ai_reply_p50",
        "ai_reply_p90", "ai_reply_max", "gt4_turn_with_cs", "gt4_turn_without_cs",
        "max_replies_rule_fired", "as_of", "reopen_reason",
    }
)


@dataclass(frozen=True)
class TicketRow:
    ticket_id: str
    cohort_week: str
    cohort_status: str
    is_weekend_start: bool
    outcome: str
    ai_first: bool
    transferred: bool
    reopen_lifetime: int | None
    reopen_within_7d: int | None
    ai_reply_count: int
    turn_count: int
    gt4_turn: bool
    issue_category: str
    app: str
    product_code: str
    skill: str | None
    intent: str | None
    tpe_code: str | None
    tpe_status: str | None
    guardrail_rule: str | None
    escalation_guard_blocked: bool
    data_quality: str

    def __post_init__(self) -> None:
        _validate_ticket_values(self)


@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: datetime
    dashboard: dict[str, object]
    tickets: tuple[TicketRow, ...]

    def dashboard_dict(self) -> dict[str, object]:
        _require_aware(self.generated_at, "generated_at")
        dashboard = deepcopy(self.dashboard)
        _validate_dashboard(dashboard, generated_at=self.generated_at)
        _validate_projected_intent_frequency(
            dashboard,
            tuple(_validated_ticket_dict(ticket) for ticket in self.tickets),
        )
        return dashboard

    def storage_dict(self) -> dict[str, object]:
        tickets = tuple(_validated_ticket_dict(ticket) for ticket in self.tickets)
        _validate_projected_intent_frequency(self.dashboard_dict(), tickets)
        return {
            "schema_version": _STORAGE_VERSION,
            "generated_at": _utc_iso(self.generated_at),
            "dashboard": self.dashboard_dict(),
            "tickets": list(tickets),
        }

    @classmethod
    def from_storage_dict(cls, value: Mapping[str, object]) -> DashboardSnapshot:
        storage = _require_mapping(value, "storage")
        _require_exact_keys(storage, {"schema_version", "generated_at", "dashboard", "tickets"}, "storage")
        if storage["schema_version"] != _STORAGE_VERSION:
            raise ValueError("unsupported dashboard storage schema_version")
        generated_at = _parse_utc_iso(storage["generated_at"], "generated_at")
        dashboard = dict(_require_mapping(storage["dashboard"], "dashboard"))
        _validate_dashboard(dashboard, generated_at=generated_at)
        raw_tickets = storage["tickets"]
        if not isinstance(raw_tickets, list):
            raise ValueError("tickets must be a list")
        tickets = tuple(_ticket_from_storage(item) for item in raw_tickets)
        _validate_projected_intent_frequency(dashboard, tuple(asdict(ticket) for ticket in tickets))
        return cls(
            generated_at=generated_at,
            dashboard=deepcopy(dashboard),
            tickets=tickets,
        )


def project_dashboard(run: ReportRun) -> DashboardSnapshot:
    result = run.result
    generated_at = result.selection.window.as_of.astimezone(timezone.utc)
    safe_intents = _projected_intents(result.sessions)
    tickets = tuple(sorted(
        (
            _ticket_row(session, safe_intents[session.session_id])
            for session in result.sessions
            if _is_safe_ticket_id(session.session_id)
        ),
        key=lambda row: (row.cohort_week, row.ticket_id),
    ))
    return DashboardSnapshot(
        generated_at,
        _dashboard_payload(run, generated_at, safe_intents),
        tickets,
    )


def ticket_page(
    snapshot: DashboardSnapshot,
    *,
    cohort_week: str | None = None,
    outcome: str | None = None,
    ticket_id: str | None = None,
    issue_category: str | None = None,
    app: str | None = None,
    product_code: str | None = None,
    skill: str | None = None,
    intent: str | None = None,
    tpe_code: str | None = None,
    gt4_turn: bool | None = None,
    transferred: bool | None = None,
    is_weekend_start: bool | None = None,
    week_definition: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, object]:
    """Return a page from the allowlisted ticket projection only.

    Dimension values are never treated as open text: every requested value is
    checked against the current safe snapshot before ticket filtering.
    """
    _validate_ticket_filters(cohort_week=cohort_week, outcome=outcome, ticket_id=ticket_id, page=page, page_size=page_size)
    strings = {
        "issue_category": issue_category,
        "app": app,
        "product_code": product_code,
        "skill": skill,
        "intent": intent,
        "tpe_code": tpe_code,
    }
    for name, value in strings.items():
        if value is None:
            continue
        if not isinstance(value, str) or value not in {
            _ticket_filter_value(ticket, name) for ticket in snapshot.tickets
        }:
            raise ValueError(f"{name} is invalid")
    for name, value in {
        "gt4_turn": gt4_turn,
        "transferred": transferred,
        "is_weekend_start": is_weekend_start,
    }.items():
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{name} is invalid")
    if week_definition is not None and week_definition not in _VIEWS:
        raise ValueError("week_definition is invalid")
    rows = [
        row for row in sorted(snapshot.tickets, key=lambda row: (row.cohort_week, row.ticket_id))
        if (cohort_week is None or row.cohort_week == cohort_week)
        and (outcome is None or row.outcome == outcome)
        and (ticket_id is None or row.ticket_id == ticket_id)
        and (issue_category is None or _ticket_filter_value(row, "issue_category") == issue_category)
        and (app is None or _ticket_filter_value(row, "app") == app)
        and (product_code is None or _ticket_filter_value(row, "product_code") == product_code)
        and (skill is None or _ticket_filter_value(row, "skill") == skill)
        and (intent is None or _ticket_filter_value(row, "intent") == intent)
        and (tpe_code is None or _ticket_filter_value(row, "tpe_code") == tpe_code)
        and (gt4_turn is None or row.gt4_turn == gt4_turn)
        and (transferred is None or row.transferred == transferred)
        and (is_weekend_start is None or row.is_weekend_start == is_weekend_start)
        and (week_definition != "mon_fri" or not row.is_weekend_start)
    ]
    start = (page - 1) * page_size
    return {"items": [asdict(row) for row in rows[start:start + page_size]], "page": page, "page_size": page_size, "total": len(rows)}


def _ticket_filter_value(ticket: TicketRow, name: str) -> str:
    value = getattr(ticket, name)
    return _MISSING if value is None else value


def _dashboard_payload(
    run: ReportRun,
    generated_at: datetime,
    safe_intents: Mapping[str, str | None],
) -> dict[str, object]:
    result = run.result
    selection = result.selection
    mon_sun = result.weekly_mon_sun or result.weekly
    mon_fri = result.weekly_mon_fri or tuple(
        summary for summary in mon_sun if summary.week_definition == "mon_fri"
    )
    views = {
        "mon_sun": _view_payload(result.sessions, mon_sun, "mon_sun", safe_intents, run.reopen_shadow),
        "mon_fri": _view_payload(result.sessions, mon_fri, "mon_fri", safe_intents, run.reopen_shadow),
    }
    quality = Counter(_quality_label(session.data_quality) for session in result.sessions)
    quality.update(_quality_label(issue.reason) for issue in selection.invalid_keyed)
    quality.update(_quality_label(issue.reason) for issue in selection.unkeyed)
    return {
        "generated_at": _utc_iso(generated_at),
        "source": {
            "traces_fetched": run.traces_fetched,
            "traces_deduplicated": run.traces_deduplicated,
            "observations_fetched": run.observations_fetched,
        },
        "enrichment_status": run.enrichment_status,
        "data_range": _data_range(mon_sun),
        "views": views,
        "coverage": _coverage(result.sessions, safe_intents),
        "unmapped_tpe_codes": _unmapped_tpe_codes(result.sessions),
        "gate_status": {
            "allowed": result.gate_status.core_allowed,
            "structural_invalid_rate": result.gate_status.structural_invalid_rate,
            "reasons": list(result.gate_status.reasons),
        },
        "data_quality": {
            "counts": dict(sorted(quality.items())),
            "weekend_start_count": sum(session.is_weekend_start for session in result.sessions),
            "left_censored_count": len(selection.left_censored),
            "pre_window_start_count": len(selection.pre_window_start),
            "invalid_keyed_session_count": len(selection.invalid_keyed),
            "unkeyed_trace_count": len(selection.unkeyed),
        },
    }


def _view_payload(
    all_sessions: tuple[SessionMetrics, ...],
    weekly: tuple[WeeklySummary, ...],
    week_definition: str,
    safe_intents: Mapping[str, str | None],
    reopen_shadow: ReopenReasonShadow,
) -> dict[str, object]:
    sessions = tuple(
        session for session in all_sessions
        if week_definition == "mon_sun" or not session.is_weekend_start
    )
    outcomes = Counter(_outcome(session.outcome) for session in sessions)
    ai_first_count = sum(session.ai_first for session in sessions)
    # This is the outcome metric defined in §9.1, not every observed later
    # transfer trace.  An unclassified first response can still be followed by
    # a transfer, which remains visible on the ticket and segment flag.
    transfer_total = outcomes["ai_then_cs"] + outcomes["direct_cs"]
    lifetime = [session.reopen_lifetime for session in sessions if session.reopen_lifetime is not None]
    within = [session.reopen_within_7d for session in sessions if session.reopen_within_7d is not None]
    gt4_with = sum(session.turn_count > 4 and session.transferred for session in sessions)
    gt4_without = sum(session.turn_count > 4 and not session.transferred for session in sessions)
    max_replies = sum("max_replies_exceeded" in session.guardrail_rules for session in sessions)
    weekly_payloads: list[dict[str, object]] = []
    for summary in weekly:
        reopen_reason = _reopen_reason_payload(summary, sessions, reopen_shadow)
        if (
            reopen_reason["status"] == "unavailable"
            and getattr(reopen_shadow, "status", None) != "unavailable"
        ):
            # One corrupt advisory aggregate invalidates this shadow as a
            # whole.  Do not show neighboring weeks as trustworthy labels.
            return _view_payload(
                all_sessions,
                weekly,
                week_definition,
                safe_intents,
                unavailable_shadow(),
            )
        weekly_payloads.append(_weekly_payload(summary, reopen_reason))
    return {
        "totals": {
            "eligible_ticket_count": len(sessions),
            "transfer_total": transfer_total,
            "gt4_turn_total": gt4_with + gt4_without,
            "weekend_start_count": sum(session.is_weekend_start for session in sessions),
        },
        "outcomes": {name: outcomes[name] for name in _OUTCOMES},
        "ai_first": {"count": ai_first_count, "rate": ai_first_count / len(sessions) if sessions else 0.0},
        "reopen": {
            "lifetime": {"numerator": sum(lifetime), "denominator": len(lifetime)},
            "within_7d": {"numerator": sum(within), "denominator": len(within)},
        },
        "weekly": weekly_payloads,
        "segments": _segments(sessions, safe_intents),
        "transfer_reasons": _transfer_reasons(sessions),
        "by_week": {
            summary.cohort_week.isoformat(): {
                "segments": _segments(
                    tuple(
                        session
                        for session in sessions
                        if session.cohort_week == summary.cohort_week
                    ),
                    safe_intents,
                ),
                "transfer_reasons": _transfer_reasons(
                    tuple(
                        session
                        for session in sessions
                        if session.cohort_week == summary.cohort_week
                    )
                ),
            }
            for summary in weekly
        },
        "rule_gt4": {
            "gt4_turn_total": gt4_with + gt4_without,
            "gt4_turn_with_cs": gt4_with,
            "gt4_turn_without_cs": gt4_without,
            "max_replies_rule_fired": max_replies,
        },
    }


def _transfer_reasons(
    sessions: tuple[SessionMetrics, ...],
) -> dict[str, object]:
    transferred = tuple(session for session in sessions if session.transferred)
    tpe_counts: Counter[tuple[str, str | None, int | None, bool]] = Counter()
    guardrail_counts: Counter[str] = Counter()
    escalation_blocked = 0
    for session in transferred:
        dims = session.dimensions
        if dims.tpe_code is not None:
            code = _safe_optional(dims.tpe_code)
            status = _safe_optional(dims.tpe_status_raw)
            if code is not None and _TPE_CODE_PATTERN.fullmatch(code):
                case = dims.tpe_case
                tpe_counts[(code, status, case, case is not None)] += 1
        # These are overlapping diagnostic indicators, not a partition of
        # transferred sessions.  Their sum may exceed the denominator and a
        # "missing reason" must never be inferred by subtraction.
        for rule in set(session.guardrail_rules):
            if rule in _GUARDRAIL_RULES:
                guardrail_counts[rule] += 1
        escalation_blocked += int(dims.escalation_guard_blocked)

    tpe_rows = [
        {
            "code": code,
            "status": status,
            "case": case,
            "mapped": mapped,
            "count": count,
        }
        for (code, status, case, mapped), count in sorted(
            tpe_counts.items(),
            key=lambda item: (
                -item[1],
                item[0][0],
                item[0][1] or "",
                item[0][2] if item[0][2] is not None else -1,
            ),
        )
    ]
    guardrail_rows = [
        {"rule": rule, "count": count}
        for rule, count in sorted(
            guardrail_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    denominator = len(transferred)
    return {
        "observed_transfer_denominator": denominator,
        "tpe": tpe_rows,
        "guardrail": guardrail_rows,
        "escalation_guard_blocked": {
            "count": escalation_blocked,
            "denominator": denominator,
        },
    }


def _segments(
    sessions: tuple[SessionMetrics, ...],
    safe_intents: Mapping[str, str | None],
) -> dict[str, dict[str, dict[str, int]]]:
    result: dict[str, dict[str, dict[str, int]]] = {}
    for dimension in _SEGMENTS:
        buckets: dict[str, dict[str, int]] = {}
        for session in sessions:
            value = _segment_value(session, dimension, safe_intents)
            bucket = buckets.setdefault(value, {"total": 0, "ai_first": 0, "transferred": 0, "reopen": 0})
            bucket["total"] += 1
            bucket["ai_first"] += int(session.ai_first)
            bucket["transferred"] += int(session.transferred)
            bucket["reopen"] += int(session.reopen_lifetime == 1)
        # The missing bucket is always present, making the consumer's closure
        # logic deterministic even when this run happens to have no missing data.
        buckets.setdefault(_MISSING, {"total": 0, "ai_first": 0, "transferred": 0, "reopen": 0})
        result[dimension] = dict(sorted(buckets.items()))
    return result


def _segment_value(
    session: SessionMetrics,
    dimension: str,
    safe_intents: Mapping[str, str | None],
) -> str:
    dims = session.dimensions
    value: str | None
    if dimension == "intent":
        value = safe_intents[session.session_id]
    elif dimension == "tpe":
        value = dims.tpe_code
    else:
        value = getattr(dims, dimension)
    return _safe_dimension(value) if isinstance(value, str) else _MISSING


def _coverage(
    sessions: tuple[SessionMetrics, ...],
    safe_intents: Mapping[str, str | None],
) -> dict[str, float]:
    if not sessions:
        return {name: 0.0 for name in ("issue_category", "app", "tpe", "intent", "skill")}
    return {
        "issue_category": sum(_segment_value(s, "issue_category", safe_intents) != _MISSING for s in sessions) / len(sessions),
        "app": sum(_segment_value(s, "app", safe_intents) != _MISSING for s in sessions) / len(sessions),
        "tpe": sum(s.dimensions.tpe_code is not None for s in sessions) / len(sessions),
        "intent": sum(safe_intents[s.session_id] is not None for s in sessions) / len(sessions),
        "skill": sum(s.dimensions.skill is not None for s in sessions) / len(sessions),
    }


def _unmapped_tpe_codes(sessions: tuple[SessionMetrics, ...]) -> list[dict[str, object]]:
    counts: Counter[tuple[str, str]] = Counter()
    for session in sessions:
        dims = session.dimensions
        if dims.tpe_code is not None and dims.tpe_case is None:
            counts[(dims.tpe_code, dims.tpe_status_raw or "")] += 1
    return [
        {"code": code, "status": status, "count": count}
        for (code, status), count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _data_range(weekly: tuple[WeeklySummary, ...]) -> dict[str, object]:
    with_data = [summary.cohort_week.isoformat() for summary in weekly if summary.has_data]
    return {
        "first_week_with_data": min(with_data) if with_data else None,
        "weeks_without_data": [summary.cohort_week.isoformat() for summary in weekly if not summary.has_data],
    }


def _ticket_row(session: SessionMetrics, safe_intent: str | None) -> TicketRow:
    dims = session.dimensions
    return TicketRow(
        ticket_id=session.session_id, cohort_week=session.cohort_week.isoformat(), cohort_status=session.cohort_status,
        is_weekend_start=session.is_weekend_start, outcome=_outcome(session.outcome), ai_first=session.ai_first,
        transferred=session.transferred, reopen_lifetime=session.reopen_lifetime,
        reopen_within_7d=session.reopen_within_7d, ai_reply_count=session.ai_reply_count,
        turn_count=session.turn_count, gt4_turn=session.turn_count > 4,
        issue_category=_safe_dimension(dims.issue_category), app=_safe_dimension(dims.app),
        product_code=_safe_dimension(dims.product_code), skill=_safe_optional(dims.skill),
        intent=safe_intent, tpe_code=_safe_optional(dims.tpe_code),
        tpe_status=_safe_optional(dims.tpe_status_raw), guardrail_rule=_safe_optional(dims.guardrail_rule),
        escalation_guard_blocked=dims.escalation_guard_blocked, data_quality=_quality_label(session.data_quality),
    )


def _projected_intents(
    sessions: tuple[SessionMetrics, ...],
) -> dict[str, str | None]:
    """Project intent once at T2–CN grain, before any browser-facing view.

    Intent originates from an LLM, not a controlled taxonomy.  A valid-looking
    identifier is still unsafe when rare: it may be customer free text.  The
    global count deliberately uses all sessions, so T2–T6 can retain a label
    whose five occurrences are split across a weekend.
    """
    valid_counts = Counter(
        intent
        for session in sessions
        for intent in (session.dimensions.intent,)
        if _is_safe_intent_label(intent)
    )
    projected: dict[str, str | None] = {}
    for session in sessions:
        raw = session.dimensions.intent
        if raw is None or (isinstance(raw, str) and not raw):
            projected[session.session_id] = None
        elif _is_safe_intent_label(raw) and valid_counts[raw] >= 5:
            projected[session.session_id] = raw
        else:
            projected[session.session_id] = "khác"
    return projected


def _weekly_payload(
    summary: WeeklySummary,
    reopen_reason: Mapping[str, object],
) -> dict[str, object]:
    if summary.as_of is None:
        raise ValueError("weekly as_of must be present")
    return {
        "cohort_week": summary.cohort_week.isoformat(), "cohort_status": summary.cohort_status,
        "week_definition": summary.week_definition, "has_data": summary.has_data,
        "total_tickets": summary.total_tickets, "ai_first_count": summary.ai_first_count,
        "ai_first_rate": summary.ai_first_rate, "ai_end_to_end_count": summary.ai_end_to_end_count,
        "ai_then_cs_count": summary.ai_then_cs_count, "direct_cs_count": summary.direct_cs_count,
        "unclassified_count": summary.unclassified_count, "reopen_7d_rate": summary.reopen_7d_rate,
        "reopen_7d_denominator": summary.reopen_7d_denominator,
        "reopen_lifetime_rate": summary.reopen_lifetime_rate,
        "reopen_lifetime_numerator": summary.reopen_lifetime_numerator,
        "reopen_lifetime_denominator": summary.reopen_lifetime_denominator,
        "ai_reply_mean_ai_first": summary.ai_reply_mean_ai_first,
        "ai_reply_p50": summary.ai_reply_p50, "ai_reply_p90": summary.ai_reply_p90,
        "ai_reply_max": summary.ai_reply_max, "gt4_turn_with_cs": summary.gt4_turn_with_cs,
        "gt4_turn_without_cs": summary.gt4_turn_without_cs,
        "max_replies_rule_fired": summary.max_replies_rule_fired, "as_of": _utc_iso(summary.as_of),
        "reopen_reason": dict(reopen_reason),
    }


def _reopen_reason_payload(
    summary: WeeklySummary,
    sessions: tuple[SessionMetrics, ...],
    shadow: ReopenReasonShadow,
) -> dict[str, object]:
    """Project shadow data without allowing it to break deterministic refresh."""
    try:
        shadow.validate()
        payload = _unchecked_reopen_reason_payload(summary, sessions, shadow)
        _validate_reopen_reason(
            payload,
            summary.reopen_7d_rate,
            summary.reopen_7d_denominator,
        )
        return payload
    except Exception:
        # The shadow is advisory only.  Keep every deterministic field usable
        # when a future label aggregation is corrupt or unsafe.
        return _unchecked_reopen_reason_payload(
            summary,
            sessions,
            unavailable_shadow(),
        )


def _unchecked_reopen_reason_payload(
    summary: WeeklySummary,
    sessions: tuple[SessionMetrics, ...],
    shadow: ReopenReasonShadow,
) -> dict[str, object]:
    weekly_sessions = tuple(
        session for session in sessions if session.cohort_week == summary.cohort_week
    )
    population = sum(
        session.ai_first
        and session.reopen_within_7d == 1
        and session.outcome in {"ai_end_to_end", "ai_then_cs"}
        and session.data_quality == "valid"
        for session in weekly_sessions
    )
    controls = [
        session.control_reopen_within_7d
        for session in weekly_sessions
        if session.outcome == "direct_cs"
        and session.control_reopen_within_7d in {0, 1}
    ]
    if summary.reopen_7d_denominator is None:
        control = {"direct_cs_reopen_7d_rate": None, "direct_cs_denominator": 0}
    else:
        denominator = len(controls)
        control = {
            "direct_cs_reopen_7d_rate": sum(controls) / denominator if denominator else None,
            "direct_cs_denominator": denominator,
        }
    if shadow.status != "labeled":
        return {
            "labels_version": shadow.labels_version,
            "status": shadow.status,
            "counts": {},
            "by_business": {},
            "coverage": {
                "population": population,
                "labeled": 0,
                "abstained": 0,
                "failed": 0,
                "invalid": 0,
            },
            "control": control,
        }

    selected = [
        item
        for item in shadow.counts
        if item.cohort_week == summary.cohort_week
        and (summary.week_definition == "mon_sun" or not item.is_weekend_start)
    ]
    selected_coverage = [
        item
        for item in shadow.coverage
        if item.cohort_week == summary.cohort_week
        and (summary.week_definition == "mon_sun" or not item.is_weekend_start)
    ]
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    businesses: dict[str, Counter[str]] = defaultdict(Counter)
    for item in selected:
        if item.count > 0:
            # A malformed shadow must not be silently collapsed into a valid
            # business bucket: that would make advisory data look trustworthy.
            _safe_string(item.issue_category, "reopen_reason business")
            counts[item.label][item.outcome] += item.count
            businesses[_safe_dimension(item.issue_category)][item.label] += item.count
    labeled = sum(sum(outcomes.values()) for outcomes in counts.values())
    return {
        "labels_version": shadow.labels_version,
        "status": "labeled",
        "counts": {
            label: dict(sorted(outcomes.items()))
            for label, outcomes in sorted(counts.items())
        },
        "by_business": {
            business: dict(sorted(labels.items()))
            for business, labels in sorted(businesses.items())
        },
        "coverage": {
            "population": population,
            "labeled": labeled,
            "abstained": sum(counts.get("other", {}).values()),
            "failed": sum(item.failed for item in selected_coverage),
            "invalid": sum(item.invalid for item in selected_coverage),
        },
        "control": control,
    }


def _validate_ticket_filters(*, cohort_week: str | None, outcome: str | None, ticket_id: str | None, page: int, page_size: int) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be at least 1")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if ticket_id is not None and not _is_safe_ticket_id(ticket_id):
        raise ValueError("ticket_id is invalid")
    if outcome is not None and outcome not in _OUTCOMES:
        raise ValueError("outcome is invalid")
    if cohort_week is not None:
        if not isinstance(cohort_week, str):
            raise ValueError("cohort_week is invalid")
        try:
            parsed = date.fromisoformat(cohort_week)
        except ValueError as error:
            raise ValueError("cohort_week is invalid") from error
        if parsed.weekday() != 0:
            raise ValueError("cohort_week must be a Monday")


def _ticket_from_storage(value: object) -> TicketRow:
    ticket = _require_mapping(value, "ticket")
    _require_exact_keys(ticket, _TICKET_KEYS, "ticket")
    try:
        return TicketRow(**dict(ticket))
    except TypeError as error:
        raise ValueError("stored ticket is invalid") from error


def _validated_ticket_dict(ticket: object) -> dict[str, object]:
    if not isinstance(ticket, TicketRow):
        raise ValueError("tickets must contain TicketRow values")
    _validate_ticket_values(ticket)
    return asdict(ticket)


def _validate_ticket_values(ticket: TicketRow) -> None:
    _validate_ticket_filters(cohort_week=ticket.cohort_week, outcome=None, ticket_id=ticket.ticket_id, page=1, page_size=1)
    if ticket.cohort_status not in {"complete", "wtd"}:
        raise ValueError("cohort_status is invalid")
    if ticket.outcome not in _OUTCOMES:
        raise ValueError("outcome is invalid")
    for value, name in ((ticket.is_weekend_start, "is_weekend_start"), (ticket.ai_first, "ai_first"), (ticket.transferred, "transferred"), (ticket.gt4_turn, "gt4_turn"), (ticket.escalation_guard_blocked, "escalation_guard_blocked")):
        if not isinstance(value, bool):
            raise ValueError(f"{name} is invalid")
    _nullable_nonnegative_int(ticket.reopen_lifetime, "reopen_lifetime")
    _nullable_nonnegative_int(ticket.reopen_within_7d, "reopen_within_7d")
    if ticket.reopen_lifetime not in {None, 0, 1}:
        raise ValueError("reopen_lifetime is invalid")
    if ticket.reopen_within_7d not in {None, 0, 1}:
        raise ValueError("reopen_within_7d is invalid")
    _nonnegative_int(ticket.ai_reply_count, "ai_reply_count")
    _positive_int(ticket.turn_count, "turn_count")
    if ticket.gt4_turn != (ticket.turn_count > 4):
        raise ValueError("gt4_turn is inconsistent")
    for value, name in ((ticket.issue_category, "issue_category"), (ticket.app, "app"), (ticket.product_code, "product_code")):
        _safe_string(value, name)
    for value, name in ((ticket.skill, "skill"), (ticket.tpe_status, "tpe_status"), (ticket.guardrail_rule, "guardrail_rule")):
        if value is not None:
            _safe_string(value, name)
    if ticket.intent is not None and ticket.intent != "khác" and not _is_safe_intent_label(ticket.intent):
        raise ValueError("intent is invalid")
    if ticket.tpe_code is not None and (
        not isinstance(ticket.tpe_code, str)
        or _TPE_CODE_PATTERN.fullmatch(ticket.tpe_code) is None
    ):
        raise ValueError("tpe_code is invalid")
    if ticket.data_quality not in _QUALITY_LABELS:
        raise ValueError("data_quality is invalid")


def _validate_dashboard(value: Mapping[str, object], *, generated_at: datetime) -> None:
    _require_exact_keys(value, _DASHBOARD_KEYS, "dashboard")
    if value["generated_at"] != _utc_iso(generated_at):
        raise ValueError("dashboard generated_at must match storage generated_at")
    _validate_count_map(value["source"], {"traces_fetched", "traces_deduplicated", "observations_fetched"}, "source")
    if value["enrichment_status"] not in {"complete", "partial"}:
        raise ValueError("enrichment_status is invalid")
    _validate_data_range(value["data_range"])
    coverage = _require_mapping(value["coverage"], "coverage")
    _require_exact_keys(coverage, {"issue_category", "app", "tpe", "intent", "skill"}, "coverage")
    for key, rate in coverage.items(): _rate(rate, f"coverage.{key}")
    _validate_unmapped(value["unmapped_tpe_codes"])
    _validate_gate(value["gate_status"])
    _validate_quality(value["data_quality"])
    views = _require_mapping(value["views"], "views")
    _require_exact_keys(views, set(_VIEWS), "views")
    for name in _VIEWS: _validate_view(views[name], name)
    if (
        views["mon_fri"]["totals"]["eligible_ticket_count"]
        + views["mon_sun"]["totals"]["weekend_start_count"]
        != views["mon_sun"]["totals"]["eligible_ticket_count"]
    ):
        raise ValueError("weekend view totals do not reconcile")


def _validate_data_range(value: object) -> None:
    mapping = _require_mapping(value, "data_range")
    _require_exact_keys(mapping, {"first_week_with_data", "weeks_without_data"}, "data_range")
    first = mapping["first_week_with_data"]
    if first is not None: _week_string(first, "data_range.first_week_with_data")
    weeks = mapping["weeks_without_data"]
    if not isinstance(weeks, list): raise ValueError("data_range.weeks_without_data is invalid")
    for week in weeks: _week_string(week, "data_range.weeks_without_data")


def _validate_unmapped(value: object) -> None:
    if not isinstance(value, list): raise ValueError("unmapped_tpe_codes must be a list")
    for item in value:
        mapping = _require_mapping(item, "unmapped_tpe_code")
        _require_exact_keys(mapping, {"code", "status", "count"}, "unmapped_tpe_code")
        _safe_string(mapping["code"], "unmapped_tpe_code.code")
        _safe_string(mapping["status"], "unmapped_tpe_code.status", allow_empty=True)
        _nonnegative_int(mapping["count"], "unmapped_tpe_code.count")


def _validate_gate(value: object) -> None:
    mapping = _require_mapping(value, "gate_status")
    _require_exact_keys(mapping, {"allowed", "structural_invalid_rate", "reasons"}, "gate_status")
    if not isinstance(mapping["allowed"], bool): raise ValueError("gate_status.allowed is invalid")
    _rate(mapping["structural_invalid_rate"], "gate_status.structural_invalid_rate")
    reasons = mapping["reasons"]
    if reasons != [] and reasons != ["structural_invalid_rate_gt_5pct"]:
        raise ValueError("gate_status.reasons is invalid")


def _validate_quality(value: object) -> None:
    mapping = _require_mapping(value, "data_quality")
    _require_exact_keys(mapping, {"counts", "weekend_start_count", "left_censored_count", "pre_window_start_count", "invalid_keyed_session_count", "unkeyed_trace_count"}, "data_quality")
    counts = _require_mapping(mapping["counts"], "data_quality.counts")
    for label, count in counts.items():
        if label not in _QUALITY_LABELS: raise ValueError("data_quality label is invalid")
        _nonnegative_int(count, "data_quality count")
    for key in set(mapping) - {"counts"}: _nonnegative_int(mapping[key], f"data_quality.{key}")


def _validate_view(value: object, expected_definition: str) -> None:
    view = _require_mapping(value, "view")
    _require_exact_keys(
        view,
        {
            "totals",
            "outcomes",
            "ai_first",
            "reopen",
            "weekly",
            "segments",
            "transfer_reasons",
            "by_week",
            "rule_gt4",
        },
        "view",
    )
    _validate_count_map(view["totals"], {"eligible_ticket_count", "transfer_total", "gt4_turn_total", "weekend_start_count"}, "view.totals")
    _validate_count_map(view["outcomes"], set(_OUTCOMES), "view.outcomes")
    if sum(view["outcomes"].values()) != view["totals"]["eligible_ticket_count"]: raise ValueError("view outcomes do not reconcile")
    if view["totals"]["transfer_total"] != view["outcomes"]["ai_then_cs"] + view["outcomes"]["direct_cs"]: raise ValueError("view transfer total does not reconcile")
    ai = _require_mapping(view["ai_first"], "view.ai_first")
    _require_exact_keys(ai, {"count", "rate"}, "view.ai_first")
    _nonnegative_int(ai["count"], "view.ai_first.count"); _rate(ai["rate"], "view.ai_first.rate")
    if ai["count"] != view["outcomes"]["ai_end_to_end"] + view["outcomes"]["ai_then_cs"]: raise ValueError("view ai_first does not reconcile")
    expected_ai_rate = (
        ai["count"] / view["totals"]["eligible_ticket_count"]
        if view["totals"]["eligible_ticket_count"]
        else 0.0
    )
    if abs(ai["rate"] - expected_ai_rate) > 1e-12:
        raise ValueError("view ai_first rate does not match division")
    reopen = _require_mapping(view["reopen"], "view.reopen")
    _require_exact_keys(reopen, {"lifetime", "within_7d"}, "view.reopen")
    for name in ("lifetime", "within_7d"):
        _validate_count_map(
            reopen[name],
            {"numerator", "denominator"},
            f"view.reopen.{name}",
        )
        counts = _require_mapping(reopen[name], f"view.reopen.{name}")
        if counts["numerator"] > counts["denominator"]:
            raise ValueError("reopen numerator exceeds denominator")
    _validate_weekly(view["weekly"], expected_definition)
    lifetime_counts = _require_mapping(
        reopen["lifetime"],
        "view.reopen.lifetime",
    )
    if (
        lifetime_counts["numerator"]
        != sum(item["reopen_lifetime_numerator"] for item in view["weekly"])
        or lifetime_counts["denominator"]
        != sum(item["reopen_lifetime_denominator"] for item in view["weekly"])
    ):
        raise ValueError("weekly lifetime does not reconcile")
    _validate_segments(view["segments"], view["totals"]["eligible_ticket_count"])
    _validate_transfer_reasons(view["transfer_reasons"], view["segments"])
    by_week = _require_mapping(view["by_week"], "view.by_week")
    weekly_by_key = {
        item["cohort_week"]: item
        for item in view["weekly"]
    }
    _require_exact_keys(by_week, set(weekly_by_key), "view.by_week")
    for cohort_week, detail_value in by_week.items():
        detail = _require_mapping(detail_value, f"view.by_week.{cohort_week}")
        _require_exact_keys(
            detail,
            {"segments", "transfer_reasons"},
            f"view.by_week.{cohort_week}",
        )
        weekly_total_for_key = weekly_by_key[cohort_week]["total_tickets"]
        _validate_segments(detail["segments"], weekly_total_for_key)
        _validate_transfer_reasons(
            detail["transfer_reasons"],
            detail["segments"],
        )
    _validate_segment_rollup(
        view["segments"],
        tuple(
            _require_mapping(detail, "view.by_week item")["segments"]
            for detail in by_week.values()
        ),
    )
    _validate_transfer_reason_rollup(
        view["transfer_reasons"],
        tuple(
            _require_mapping(detail, "view.by_week item")["transfer_reasons"]
            for detail in by_week.values()
        ),
    )
    rule = _require_mapping(view["rule_gt4"], "view.rule_gt4")
    _validate_count_map(rule, {"gt4_turn_total", "gt4_turn_with_cs", "gt4_turn_without_cs", "max_replies_rule_fired"}, "view.rule_gt4")
    if rule["gt4_turn_total"] != rule["gt4_turn_with_cs"] + rule["gt4_turn_without_cs"]: raise ValueError("rule_gt4 does not reconcile")
    if rule["gt4_turn_total"] != view["totals"]["gt4_turn_total"]: raise ValueError("rule_gt4 total does not reconcile")
    if (
        rule["gt4_turn_with_cs"]
        != sum(item["gt4_turn_with_cs"] for item in view["weekly"])
        or rule["gt4_turn_without_cs"]
        != sum(item["gt4_turn_without_cs"] for item in view["weekly"])
        or rule["max_replies_rule_fired"]
        != sum(item["max_replies_rule_fired"] for item in view["weekly"])
    ):
        raise ValueError("weekly rule_gt4 does not reconcile")
    weekly_total = sum(item["total_tickets"] for item in view["weekly"])
    if weekly_total != view["totals"]["eligible_ticket_count"]: raise ValueError("view weekly does not reconcile")


def _validate_transfer_reasons(
    value: object,
    segments_value: object,
) -> None:
    reasons = _require_mapping(value, "transfer_reasons")
    _require_exact_keys(
        reasons,
        {
            "observed_transfer_denominator",
            "tpe",
            "guardrail",
            "escalation_guard_blocked",
        },
        "transfer_reasons",
    )
    denominator = _nonnegative_int(
        reasons["observed_transfer_denominator"],
        "transfer_reasons.observed_transfer_denominator",
    )
    segments = _require_mapping(segments_value, "segments")
    for dimension in _SEGMENTS:
        buckets = _require_mapping(
            segments[dimension],
            f"segments.{dimension}",
        )
        transferred_total = sum(
            _require_mapping(counts, "segment counts")["transferred"]
            for counts in buckets.values()
        )
        if transferred_total != denominator:
            raise ValueError("transfer reason denominator does not reconcile")

    tpe_rows = reasons["tpe"]
    if not isinstance(tpe_rows, list):
        raise ValueError("transfer_reasons.tpe must be a list")
    seen_tpe: set[tuple[str, str | None, int | None, bool]] = set()
    tpe_count = 0
    for raw_row in tpe_rows:
        row = _require_mapping(raw_row, "transfer_reasons.tpe item")
        _require_exact_keys(
            row,
            {"code", "status", "case", "mapped", "count"},
            "transfer_reasons.tpe item",
        )
        code = row["code"]
        if not isinstance(code, str) or _TPE_CODE_PATTERN.fullmatch(code) is None:
            raise ValueError("transfer_reasons.tpe code is invalid")
        status = row["status"]
        if status is not None:
            status = _safe_string(status, "transfer_reasons.tpe status")
        case = row["case"]
        if case is not None:
            _nonnegative_int(case, "transfer_reasons.tpe case")
        mapped = row["mapped"]
        if not isinstance(mapped, bool) or mapped != (case is not None):
            raise ValueError("transfer_reasons.tpe mapped is invalid")
        count = _positive_int(row["count"], "transfer_reasons.tpe count")
        key = (code, status, case, mapped)
        if key in seen_tpe:
            raise ValueError("transfer_reasons.tpe rows must be unique")
        seen_tpe.add(key)
        tpe_count += count
    if tpe_count > denominator:
        raise ValueError("transfer_reasons.tpe exceeds denominator")

    guardrail_rows = reasons["guardrail"]
    if not isinstance(guardrail_rows, list):
        raise ValueError("transfer_reasons.guardrail must be a list")
    # Each rule is bounded independently.  Rules can overlap on a session, so
    # their combined count is intentionally not bounded by the denominator.
    seen_rules: set[str] = set()
    for raw_row in guardrail_rows:
        row = _require_mapping(raw_row, "transfer_reasons.guardrail item")
        _require_exact_keys(
            row,
            {"rule", "count"},
            "transfer_reasons.guardrail item",
        )
        rule = row["rule"]
        if rule not in _GUARDRAIL_RULES or rule in seen_rules:
            raise ValueError("transfer_reasons.guardrail rule is invalid")
        seen_rules.add(rule)
        count = _positive_int(
            row["count"],
            "transfer_reasons.guardrail count",
        )
        if count > denominator:
            raise ValueError("transfer_reasons.guardrail exceeds denominator")

    escalation = _require_mapping(
        reasons["escalation_guard_blocked"],
        "transfer_reasons.escalation_guard_blocked",
    )
    _require_exact_keys(
        escalation,
        {"count", "denominator"},
        "transfer_reasons.escalation_guard_blocked",
    )
    count = _nonnegative_int(
        escalation["count"],
        "transfer_reasons.escalation_guard_blocked.count",
    )
    escalation_denominator = _nonnegative_int(
        escalation["denominator"],
        "transfer_reasons.escalation_guard_blocked.denominator",
    )
    if escalation_denominator != denominator or count > denominator:
        raise ValueError("transfer_reasons escalation does not reconcile")


def _validate_transfer_reason_rollup(
    aggregate_value: object,
    weekly_values: tuple[object, ...],
) -> None:
    aggregate = _require_mapping(aggregate_value, "transfer_reasons")
    weekly = tuple(
        _require_mapping(value, "weekly transfer_reasons")
        for value in weekly_values
    )
    if aggregate["observed_transfer_denominator"] != sum(
        value["observed_transfer_denominator"] for value in weekly
    ):
        raise ValueError("transfer reason weekly denominator does not reconcile")

    def row_counter(
        value: Mapping[str, object],
        field: str,
        keys: tuple[str, ...],
    ) -> Counter[tuple[object, ...]]:
        return Counter(
            {
                tuple(row[key] for key in keys): row["count"]
                for row in value[field]
            }
        )

    aggregate_tpe = row_counter(
        aggregate,
        "tpe",
        ("code", "status", "case", "mapped"),
    )
    weekly_tpe: Counter[tuple[object, ...]] = Counter()
    aggregate_guardrail = row_counter(
        aggregate,
        "guardrail",
        ("rule",),
    )
    weekly_guardrail: Counter[tuple[object, ...]] = Counter()
    for value in weekly:
        weekly_tpe.update(
            row_counter(value, "tpe", ("code", "status", "case", "mapped"))
        )
        weekly_guardrail.update(
            row_counter(value, "guardrail", ("rule",))
        )
    if aggregate_tpe != weekly_tpe or aggregate_guardrail != weekly_guardrail:
        raise ValueError("transfer reason weekly rows do not reconcile")
    aggregate_escalation = _require_mapping(
        aggregate["escalation_guard_blocked"],
        "transfer_reasons.escalation_guard_blocked",
    )
    if aggregate_escalation["count"] != sum(
        _require_mapping(
            value["escalation_guard_blocked"],
            "weekly escalation_guard_blocked",
        )["count"]
        for value in weekly
    ):
        raise ValueError("transfer reason weekly escalation does not reconcile")


def _validate_segment_rollup(
    aggregate_value: object,
    weekly_values: tuple[object, ...],
) -> None:
    aggregate = _require_mapping(aggregate_value, "segments")
    weekly = tuple(
        _require_mapping(value, "weekly segments")
        for value in weekly_values
    )
    fields = ("total", "ai_first", "transferred", "reopen")
    for dimension in _SEGMENTS:
        aggregate_buckets = _require_mapping(
            aggregate[dimension],
            f"segments.{dimension}",
        )
        weekly_labels: set[object] = set()
        weekly_counts: defaultdict[object, Counter[str]] = defaultdict(Counter)
        for segments in weekly:
            buckets = _require_mapping(
                segments[dimension],
                f"weekly segments.{dimension}",
            )
            weekly_labels.update(buckets)
            for label, raw_counts in buckets.items():
                counts = _require_mapping(raw_counts, "weekly segment counts")
                for field in fields:
                    weekly_counts[label][field] += counts[field]
        expected_labels = weekly_labels or {_MISSING}
        if set(aggregate_buckets) != expected_labels:
            raise ValueError(
                f"segment weekly rows do not reconcile for {dimension}"
            )
        for label, raw_counts in aggregate_buckets.items():
            counts = _require_mapping(raw_counts, "segment counts")
            if any(
                counts[field] != weekly_counts[label][field]
                for field in fields
            ):
                raise ValueError(
                    f"segment weekly rows do not reconcile for {dimension}"
                )


def _validate_segments(value: object, total: object) -> None:
    segments = _require_mapping(value, "segments")
    _require_exact_keys(segments, set(_SEGMENTS), "segments")
    for name in _SEGMENTS:
        buckets = _require_mapping(segments[name], f"segments.{name}")
        if _MISSING not in buckets: raise ValueError("segments must include missing bucket")
        summed = 0
        for label, counts in buckets.items():
            _validate_segment_label(name, label)
            _validate_count_map(counts, {"total", "ai_first", "transferred", "reopen"}, f"segments.{name}")
            summed += counts["total"]
        if summed != total: raise ValueError("segment totals do not reconcile")


def _validate_segment_label(dimension: str, value: object) -> None:
    if dimension == "intent":
        if value == _MISSING or value == "khác":
            return
        if not _is_safe_intent_label(value):
            raise ValueError("intent segment label is invalid")
        return
    _safe_string(value, f"segments.{dimension} label")


def _validate_projected_intent_frequency(
    dashboard: Mapping[str, object],
    tickets: tuple[dict[str, object], ...],
) -> None:
    """Defence in depth for persisted/browser-ready intent values.

    Ticket Explorer deliberately excludes non-numeric session IDs, so its rows
    are not the cohort denominator.  The T2–CN intent segment is the full
    population and is therefore the authoritative global frequency source.
    """
    views = _require_mapping(dashboard["views"], "views")
    mon_sun = _require_mapping(views["mon_sun"], "views.mon_sun")
    mon_sun_segments = _require_mapping(mon_sun["segments"], "views.mon_sun.segments")
    global_buckets = _require_mapping(mon_sun_segments["intent"], "views.mon_sun.segments.intent")
    global_counts = {
        label: bucket["total"]
        for label, bucket in global_buckets.items()
        if label not in {_MISSING, "khác"}
        and isinstance(bucket, Mapping)
        and isinstance(bucket.get("total"), int)
    }
    for intent, count in global_counts.items():
        if not _is_safe_intent_label(intent) or count < 5:
            raise ValueError("intent is not approved for snapshot storage")
    for ticket in tickets:
        intent = ticket.get("intent")
        if intent is not None and intent != "khác" and (
            not isinstance(intent, str) or intent not in global_counts
        ):
            raise ValueError("intent is not approved for snapshot storage")
    for view in views.values():
        projected_view = _require_mapping(view, "view")
        segments = _require_mapping(projected_view["segments"], "segments")
        intent_buckets = _require_mapping(segments["intent"], "segments.intent")
        for label in intent_buckets:
            if label in {_MISSING, "khác"}:
                continue
            if not _is_safe_intent_label(label) or global_counts.get(label, 0) < 5:
                raise ValueError("intent segment is not approved for snapshot storage")
        by_week = _require_mapping(projected_view["by_week"], "view.by_week")
        for detail_value in by_week.values():
            detail = _require_mapping(detail_value, "view.by_week item")
            weekly_segments = _require_mapping(
                detail["segments"],
                "view.by_week segments",
            )
            weekly_intents = _require_mapping(
                weekly_segments["intent"],
                "view.by_week segments.intent",
            )
            for label in weekly_intents:
                if label in {_MISSING, "khác"}:
                    continue
                if (
                    not _is_safe_intent_label(label)
                    or global_counts.get(label, 0) < 5
                ):
                    raise ValueError(
                        "intent by-week segment is not approved for snapshot storage"
                    )


def _validate_weekly(value: object, expected_definition: str) -> None:
    if not isinstance(value, list): raise ValueError("weekly must be a list")
    for summary in value:
        item = _require_mapping(summary, "weekly item")
        _require_exact_keys(item, _WEEKLY_KEYS, "weekly item")
        _week_string(item["cohort_week"], "weekly cohort_week")
        if item["cohort_status"] not in {"complete", "wtd"}: raise ValueError("weekly cohort_status is invalid")
        if item["week_definition"] != expected_definition: raise ValueError("weekly week_definition is invalid")
        if not isinstance(item["has_data"], bool): raise ValueError("weekly has_data is invalid")
        for field in ("total_tickets", "ai_first_count", "ai_end_to_end_count", "ai_then_cs_count", "direct_cs_count", "unclassified_count", "reopen_lifetime_numerator", "reopen_lifetime_denominator", "gt4_turn_with_cs", "gt4_turn_without_cs", "max_replies_rule_fired"):
            _nonnegative_int(item[field], f"weekly {field}")
        if item["has_data"] != bool(item["total_tickets"]): raise ValueError("weekly has_data does not match total")
        if item["ai_first_count"] != item["ai_end_to_end_count"] + item["ai_then_cs_count"]: raise ValueError("weekly ai_first does not reconcile")
        if item["total_tickets"] != item["ai_end_to_end_count"] + item["ai_then_cs_count"] + item["direct_cs_count"] + item["unclassified_count"]: raise ValueError("weekly outcomes do not reconcile")
        _rate(item["ai_first_rate"], "weekly ai_first_rate")
        expected_ai_rate = (
            item["ai_first_count"] / item["total_tickets"]
            if item["total_tickets"]
            else 0.0
        )
        if abs(item["ai_first_rate"] - expected_ai_rate) > 1e-12:
            raise ValueError("weekly ai_first_rate does not match division")
        _nullable_rate(item["reopen_7d_rate"], "weekly reopen_7d_rate")
        _nullable_nonnegative_int(item["reopen_7d_denominator"], "weekly reopen_7d_denominator")
        _nullable_rate(item["reopen_lifetime_rate"], "weekly reopen_lifetime_rate")
        reopen_7d_rate = item["reopen_7d_rate"]
        reopen_7d_denominator = item["reopen_7d_denominator"]
        if reopen_7d_denominator in {None, 0}:
            if reopen_7d_rate is not None:
                raise ValueError("weekly reopen_7d_rate does not match division")
        elif reopen_7d_rate is None or abs(
            reopen_7d_rate * reopen_7d_denominator
            - round(reopen_7d_rate * reopen_7d_denominator)
        ) > 1e-9:
            raise ValueError("weekly reopen_7d_rate does not match division")
        lifetime_numerator = item["reopen_lifetime_numerator"]
        lifetime_denominator = item["reopen_lifetime_denominator"]
        if lifetime_numerator > lifetime_denominator:
            raise ValueError("weekly reopen numerator exceeds denominator")
        expected_lifetime_rate = (
            lifetime_numerator / lifetime_denominator
            if lifetime_denominator
            else None
        )
        if (
            (expected_lifetime_rate is None)
            != (item["reopen_lifetime_rate"] is None)
            or (
                expected_lifetime_rate is not None
                and abs(
                    item["reopen_lifetime_rate"] - expected_lifetime_rate
                )
                > 1e-12
            )
        ):
            raise ValueError(
                "weekly reopen_lifetime_rate does not match division"
            )
        _nullable_nonnegative_number(item["ai_reply_mean_ai_first"], "weekly ai_reply_mean_ai_first")
        for field in ("ai_reply_p50", "ai_reply_p90", "ai_reply_max"): _nullable_nonnegative_int(item[field], f"weekly {field}")
        _parse_utc_iso(item["as_of"], "weekly as_of")
        _validate_reopen_reason(
            item["reopen_reason"],
            item["reopen_7d_rate"],
            item["reopen_7d_denominator"],
        )


def _validate_reopen_reason(
    value: object,
    reopen_7d_rate: object,
    reopen_7d_denominator: object,
) -> None:
    reason = _require_mapping(value, "reopen_reason")
    _require_exact_keys(
        reason,
        {"labels_version", "status", "counts", "by_business", "coverage", "control"},
        "reopen_reason",
    )
    if not isinstance(reason["labels_version"], str) or re.fullmatch(r"v[0-9]+", reason["labels_version"]) is None:
        raise ValueError("reopen_reason labels_version is invalid")
    status = reason["status"]
    if status not in {"pending", "labeled", "unavailable"}:
        raise ValueError("reopen_reason status is invalid")
    coverage = _require_mapping(reason["coverage"], "reopen_reason coverage")
    _require_exact_keys(
        coverage,
        {"population", "labeled", "abstained", "failed", "invalid"},
        "reopen_reason coverage",
    )
    for field in coverage:
        _nonnegative_int(coverage[field], f"reopen_reason coverage {field}")
    counts = _require_mapping(reason["counts"], "reopen_reason counts")
    businesses = _require_mapping(reason["by_business"], "reopen_reason by_business")
    count_total = 0
    abstained = 0
    for label, outcomes_value in counts.items():
        if not isinstance(label, str) or _INTENT_PATTERN.fullmatch(label) is None:
            raise ValueError("reopen_reason label is invalid")
        outcomes = _require_mapping(outcomes_value, "reopen_reason outcomes")
        if not outcomes or not set(outcomes).issubset({"ai_end_to_end", "ai_then_cs"}):
            raise ValueError("reopen_reason outcomes are invalid")
        for outcome_count in outcomes.values():
            count_total += _positive_int(outcome_count, "reopen_reason count")
            if label == "other":
                abstained += outcome_count
    business_by_label: Counter[str] = Counter()
    for business, labels_value in businesses.items():
        _safe_string(business, "reopen_reason business")
        labels = _require_mapping(labels_value, "reopen_reason business labels")
        if not labels:
            raise ValueError("reopen_reason business labels are invalid")
        for label, label_count in labels.items():
            if not isinstance(label, str) or _INTENT_PATTERN.fullmatch(label) is None:
                raise ValueError("reopen_reason label is invalid")
            business_by_label[label] += _positive_int(label_count, "reopen_reason business count")
    if status == "labeled":
        if (
            count_total != coverage["labeled"]
            or business_by_label
            != Counter(
                {
                    label: sum(_require_mapping(outcomes, "reopen_reason outcomes").values())
                    for label, outcomes in counts.items()
                }
            )
            or abstained != coverage["abstained"]
            or coverage["abstained"] > coverage["labeled"]
            or coverage["population"]
            != coverage["labeled"] + coverage["failed"] + coverage["invalid"]
        ):
            raise ValueError("reopen_reason coverage does not reconcile")
    elif counts or businesses or any(coverage[field] for field in ("labeled", "abstained", "failed", "invalid")):
        raise ValueError("reopen_reason non-labeled status must be empty")
    control = _require_mapping(reason["control"], "reopen_reason control")
    _require_exact_keys(
        control,
        {"direct_cs_reopen_7d_rate", "direct_cs_denominator"},
        "reopen_reason control",
    )
    denominator = _nonnegative_int(control["direct_cs_denominator"], "reopen_reason control denominator")
    rate = control["direct_cs_reopen_7d_rate"]
    _nullable_rate(rate, "reopen_reason control rate")
    if denominator == 0 and rate is not None:
        raise ValueError("reopen_reason control rate does not match denominator")
    if denominator > 0:
        if rate is None or abs(rate * denominator - round(rate * denominator)) > 1e-9:
            raise ValueError("reopen_reason control rate does not match denominator")
    if reopen_7d_denominator is None and (denominator != 0 or rate is not None):
        raise ValueError("reopen_reason immature control is invalid")


def _safe_dimension(value: str) -> str:
    try:
        return _safe_string(value, "dimension")
    except ValueError:
        return _MISSING


def _is_safe_ticket_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and _TICKET_ID_PATTERN.fullmatch(value) is not None
        and _PHONE.search(value) is None
    )


def _safe_optional(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return _safe_string(value, "dimension")
    except ValueError:
        return None


def _safe_string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 256 or (not allow_empty and not value.strip()): raise ValueError(f"{name} is invalid")
    cleaned = normalize("NFC", value.strip())
    if (
        _PHONE.search(cleaned) or _UUID.search(cleaned) or _EMAIL.search(cleaned)
        or _URL.search(cleaned) or any(category(character).startswith("C") for character in cleaned)
        or _contains_long_numeric_identifier(cleaned) or _looks_like_vietnamese_personal_name(cleaned)
    ):
        raise ValueError(f"{name} is unsafe")
    return cleaned


def _is_safe_intent_label(value: object) -> bool:
    """Return true only for a non-identifying, canonical intent label.

    The syntax permitlist alone is insufficient: phone numbers, UUIDs and
    opaque numeric identifiers all satisfy the character class.  Keep this
    predicate independent of the projector so storage validation uses the
    exact same privacy boundary.
    """
    if not isinstance(value, str) or _INTENT_PATTERN.fullmatch(value) is None:
        return False
    return not (
        _PHONE.search(value)
        or _UUID.search(value)
        or _EMAIL.search(value)
        or _URL.search(value)
        or any(category(character).startswith("C") for character in value)
        or _contains_long_numeric_identifier(value)
    )


def _contains_long_numeric_identifier(value: str) -> bool:
    run_length = 0
    for character in value:
        try:
            decimal(character)
        except ValueError:
            run_length = 0
        else:
            run_length += 1
            if run_length >= 6:
                return True
    return False


def _looks_like_vietnamese_personal_name(value: str) -> bool:
    parts = value.casefold().split()
    return (
        len(parts) == 3
        and parts[0] in _VIETNAMESE_FAMILY_NAMES
        and parts[1] in _VIETNAMESE_NAME_MIDDLES
        and parts[2].isalpha()
        and 1 <= len(parts[2]) <= 32
    )


def _week_string(value: object, name: str) -> None:
    if not isinstance(value, str): raise ValueError(f"{name} is invalid")
    try: parsed = date.fromisoformat(value)
    except ValueError as error: raise ValueError(f"{name} is invalid") from error
    if parsed.weekday() != 0: raise ValueError(f"{name} must be a Monday")


def _validate_count_map(value: object, keys: set[str] | frozenset[str], name: str) -> None:
    mapping = _require_mapping(value, name); _require_exact_keys(mapping, keys, name)
    for count in mapping.values(): _nonnegative_int(count, name)


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value): raise ValueError(f"{name} must be an object")
    return value


def _require_exact_keys(value: Mapping[str, object], keys: set[str] | frozenset[str], name: str) -> None:
    if set(value) != set(keys): raise ValueError(f"{name} has unsupported or missing fields")


def _parse_utc_iso(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"): raise ValueError(f"{name} must be a UTC ISO timestamp ending in Z")
    try: parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error: raise ValueError(f"{name} must be a valid ISO timestamp") from error
    _require_aware(parsed, name); return parsed.astimezone(timezone.utc)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError(f"{name} must be timezone-aware")


def _utc_iso(value: datetime) -> str:
    _require_aware(value, "datetime"); return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0: raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nullable_nonnegative_int(value: object, name: str) -> int | None:
    return None if value is None else _nonnegative_int(value, name)


def _rate(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1: raise ValueError(f"{name} must be a rate")
    return float(value)


def _nullable_rate(value: object, name: str) -> float | None:
    return None if value is None else _rate(value, name)


def _nullable_nonnegative_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)


def _outcome(value: str | None) -> str:
    return value if value in _OUTCOMES else "unclassified"


def _quality_label(value: object) -> str:
    return value if value in _QUALITY_LABELS else "unknown_quality_issue"
