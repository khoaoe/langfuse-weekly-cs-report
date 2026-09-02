from __future__ import annotations

"""The deliberately small, privacy-safe browser/storage projection.

Raw Langfuse traces never cross this boundary.  This module is also the one
place that defines the persisted browser contract, so a schema change cannot
accidentally grow an unreviewed JSON surface.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import AbstractSet, Mapping, Sequence
from unicodedata import category, decimal, normalize
from zoneinfo import ZoneInfo

from .csat_cache import CSATCache, CachedCSATResponse
from .enrichment import build_tpe_status_index
from .entry_coverage_cache import (
    ENTRY_COVERAGE_START_WEEK,
    EntryCoverageCache,
    EntryCoverageCacheError,
    EntryCoverageRecord,
)
from .reconciliation_cache import ReconciliationCache
from .models import AnalysisResult, SessionMetrics, WeeklySummary
from .pipeline import SamePeriodComparison, summarize_same_period
from .reopen_shadow import ReopenReasonShadow, unavailable_shadow
from .report import ReportRun


_STORAGE_VERSION = 24
_TICKET_ID_PATTERN = re.compile(r"[1-9][0-9]{0,19}\Z")
_PHONE = re.compile(r"(?:^|\D)(?:0|84|\+84)[0-9]{8,10}(?:$|\D)")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_INTENT_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
_TPE_CODE_PATTERN = re.compile(r"-?[0-9]{1,6}\Z")
_NATURAL_SORT_PART = re.compile(r"([0-9]+)")
_TICKET_SORT_DIRECTIONS = frozenset({"asc", "desc"})
_GUARDRAIL_RULES = frozenset(
    {
        "cs_escalation",
        "empty_input",
        "empty_message_marker",
        "max_replies_exceeded",
        "missing_transaction_id",
        "off_topic_llm",
        "prompt_injection",
        "prompt_injection_llm",
        "off_topic",
        "system_prompt_leak",
        "tone_check_error",
    }
)
_TRANSFER_TRIGGER_REASONS = frozenset(
    {
        "skill_suggested_transfer",
        "ai_response_requires_transfer",
        "missing_transaction_id",
        "max_replies_exceeded",
        "out_of_scope",
        "empty_message",
        "prompt_injection",
        "output_check_error",
        "other_guardrail",
        "unknown",
    }
)
_TRANSFER_TRIGGER_SOURCES = frozenset(
    {"input_guardrail", "skill_guardrail_checked", "output_guardrail"}
)
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_COMMENT_URL = re.compile(
    rf"{_URL.pattern}"
    r"|(?<![\w])(?:"
    r"(?:mailto|tel|sms|data|javascript|geo|urn):\S+"
    r"|[a-z][a-z0-9+.-]*:(?://\S+|[^\s:/?#]+[/?#]\S*)"
    r")"
    r"|(?<![\w@])(?:[^\W_](?:[\w-]{0,61}[^\W_])?\.)+"
    r"[^\W\d_]{2,63}(?::\d{1,5})?(?:[/?#]\S*)?"
    r"|(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}"
    r"(?::\d{1,5})?(?:[/?#]\S*)?"
    r"|\[[0-9a-f:.%]+\](?::\d{1,5})?(?:[/?#]\S*)?"
    r"|(?<![\w:])(?:[0-9a-f]{0,4}:)*[0-9a-f]{0,4}::"
    r"(?:[0-9a-f]{0,4}:)*[0-9a-f]{0,4}(?:[/?#]\S*)?"
    r"|(?<![\w:])(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}"
    r"(?:[/?#]\S*)?",
    re.IGNORECASE,
)
_UTC_ISO = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)
_VIETNAMESE_FAMILY_NAMES = frozenset({
    "nguyễn", "nguyen", "trần", "tran", "lê", "le", "phạm", "pham", "hoàng", "hoang", "huỳnh", "huynh", "vũ", "vu", "võ", "vo", "đặng", "dang", "bùi", "bui", "đỗ", "do", "hồ", "ho", "ngô", "ngo", "dương", "duong", "lý", "ly",
})
_VIETNAMESE_NAME_MIDDLES = frozenset({"văn", "van", "thị", "thi"})
_OUTCOMES = ("ai_end_to_end", "ai_then_cs", "direct_cs", "unclassified")
_CSAT_BUCKETS = ("positive", "neutral", "negative")
_CSAT_TICKET_STATES = frozenset({*_CSAT_BUCKETS, "unrated"})
_CSAT_SORT_RANK = {"negative": 0, "neutral": 1, "positive": 2}
_VIEWS = ("mon_sun", "mon_fri")
_ENTRY_COVERAGE_STATUSES = frozenset(
    {
        "ai_replied_only",
        "ai_replied_then_transferred",
        "transferred_without_ai_reply",
        "invoked_no_result",
        "not_observed_invoked",
        "unresolved",
    }
)
_VIETNAM_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
_SEGMENTS = (
    "issue_category",
    "app",
    "product_code",
    "skill",
    "intent",
    "tpe",
    "guardrail_rule",
    "entry_point",
    "model_core",
)
_MISSING = "Không xác định"
# `skill` never used _MISSING accurately: a ticket with three distinct skills
# and a ticket with zero `execute` observations both collapsed to the same
# label. These name the two real cases instead.
_MULTI_SKILL = "Nhiều skill"
_NO_SKILL = "Chưa ghi nhận"
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
        "ticket_id", "opened_at", "cohort_week", "cohort_status", "is_weekend_start", "outcome",
        "ai_first", "transferred", "reopen_lifetime", "reopen_within_7d",
        "ai_reply_count", "turn_count", "gt4_turn", "issue_category", "app",
        "product_code", "skill", "intent", "tpe_code", "tpe_status",
        "guardrail_rule", "transfer_reason", "escalation_guard_blocked", "csat_satisfaction",
        "data_quality", "model_core",
        # Day-grain diagnostic fields (§4.1) -- server-only, never part of the
        # Ticket Explorer's public projection (`_TICKET_EXPLORER_PUBLIC_KEYS`).
        "transfer_rule", "transfer_source", "transfer_stage", "transfer_skill",
        "guardrail_rules", "tpe_signals",
    }
)
# The public shape `ticket_page()` (non-aggregate) returns to the browser.
# Deliberately excludes the day-grain diagnostic fields above: they only
# exist to let day aggregates reconstruct the weekly transfer/TPE grain and
# must never reach the Ticket Explorer projection (§4.1 privacy contract).
_TICKET_EXPLORER_PUBLIC_KEYS = _TICKET_KEYS - {
    "transfer_rule", "transfer_source", "transfer_stage", "transfer_skill",
    "guardrail_rules", "tpe_signals",
}
_WEEKLY_KEYS = frozenset(
    {
        "cohort_week", "cohort_status", "week_definition", "has_data",
        "total_tickets", "ai_first_count", "ai_first_rate", "ai_end_to_end_count",
        "ai_then_cs_count", "direct_cs_count", "unclassified_count", "reopen_7d_rate",
        "reopen_7d_denominator", "reopen_lifetime_rate", "reopen_lifetime_numerator",
        "reopen_lifetime_denominator", "ai_reply_sum_ai_first",
        "ai_reply_mean_ai_first", "ai_reply_p50",
        "ai_reply_p90", "ai_reply_max", "gt4_turn_with_cs", "gt4_turn_without_cs",
        "max_replies_rule_fired", "resolved_first_reply", "as_of", "reopen_reason",
    }
)


@dataclass(frozen=True)
class TicketRow:
    ticket_id: str
    opened_at: str
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
    transfer_reason: str | None
    escalation_guard_blocked: bool
    csat_satisfaction: str | None
    data_quality: str
    model_core: str | None = None
    # Day-grain diagnostic fields (§4.1). Default empty/None so tickets built
    # before this field set existed still construct; a bumped
    # `_STORAGE_VERSION` means old *stored* snapshots never reach this
    # constructor anyway (`dashboard_cache.py` regenerates on version
    # mismatch instead of migrating field-by-field).
    transfer_rule: str | None = None
    transfer_source: str | None = None
    transfer_stage: str | None = None
    transfer_skill: str | None = None
    guardrail_rules: tuple[str, ...] = ()
    tpe_signals: tuple[tuple[str, str | None, str | None], ...] = ()

    def __post_init__(self) -> None:
        _validate_ticket_values(self)


@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: datetime
    dashboard: dict[str, object]
    tickets: tuple[TicketRow, ...]
    entry_coverage_tickets: tuple[EntryCoverageRecord, ...] = ()

    def dashboard_dict(self) -> dict[str, object]:
        _require_aware(self.generated_at, "generated_at")
        dashboard = deepcopy(self.dashboard)
        _validate_dashboard(dashboard, generated_at=self.generated_at)
        _validate_projected_intent_frequency(
            dashboard,
            tuple(_validated_ticket_dict(ticket) for ticket in self.tickets),
        )
        _validate_entry_coverage_records(self.entry_coverage_tickets)
        return dashboard

    def storage_dict(self) -> dict[str, object]:
        tickets = tuple(_validated_ticket_dict(ticket) for ticket in self.tickets)
        _validate_projected_intent_frequency(self.dashboard_dict(), tickets)
        _validate_entry_coverage_records(self.entry_coverage_tickets)
        return {
            "schema_version": _STORAGE_VERSION,
            "generated_at": _utc_iso(self.generated_at),
            "dashboard": self.dashboard_dict(),
            "tickets": list(tickets),
            "entry_coverage_tickets": [
                _entry_coverage_record_dict(record)
                for record in self.entry_coverage_tickets
            ],
        }

    @classmethod
    def from_storage_dict(cls, value: Mapping[str, object]) -> DashboardSnapshot:
        storage = _require_mapping(value, "storage")
        _require_exact_keys(
            storage,
            {
                "schema_version",
                "generated_at",
                "dashboard",
                "tickets",
                "entry_coverage_tickets",
            },
            "storage",
        )
        if storage["schema_version"] != _STORAGE_VERSION:
            raise ValueError("unsupported dashboard storage schema_version")
        generated_at = _parse_utc_iso(storage["generated_at"], "generated_at")
        dashboard = dict(_require_mapping(storage["dashboard"], "dashboard"))
        _validate_dashboard(dashboard, generated_at=generated_at)
        raw_tickets = storage["tickets"]
        if not isinstance(raw_tickets, list):
            raise ValueError("tickets must be a list")
        tickets = tuple(_ticket_from_storage(item) for item in raw_tickets)
        raw_entry_tickets = storage["entry_coverage_tickets"]
        if not isinstance(raw_entry_tickets, list):
            raise ValueError("entry_coverage_tickets must be a list")
        entry_tickets = tuple(
            _entry_coverage_record_from_storage(item)
            for item in raw_entry_tickets
        )
        _validate_entry_coverage_records(entry_tickets)
        _validate_projected_intent_frequency(dashboard, tuple(asdict(ticket) for ticket in tickets))
        return cls(
            generated_at=generated_at,
            dashboard=deepcopy(dashboard),
            tickets=tickets,
            entry_coverage_tickets=entry_tickets,
        )


def project_dashboard(
    run: ReportRun,
    *,
    csat_cache: CSATCache | None = None,
    reconciliation_cache: ReconciliationCache | None = None,
    entry_coverage_cache: EntryCoverageCache | None = None,
) -> DashboardSnapshot:
    result = run.result
    generated_at = result.selection.window.as_of.astimezone(timezone.utc)
    safe_intents = _projected_intents(result.sessions)
    ordered_csat = _ordered_csat_by_ticket(
        csat_cache.responses if csat_cache is not None else ()
    )
    # Built once here and threaded into `_ticket_row()` so each ticket can
    # bake in a resolved TPE status at generation time -- day aggregates
    # read only stored `TicketRow`s later, when the taxonomy is gone.
    tpe_status_index = build_tpe_status_index(result.sessions, run.taxonomy)
    tickets = tuple(sorted(
        (
            _ticket_row(
                session,
                safe_intents[session.session_id],
                csat_cache,
                ordered_csat,
                tpe_status_index,
            )
            for session in result.sessions
            if _is_safe_ticket_id(session.session_id)
        ),
        key=lambda row: (row.cohort_week, row.ticket_id),
    ))
    return DashboardSnapshot(
        generated_at,
        _dashboard_payload(
            run,
            generated_at,
            safe_intents,
            csat_cache,
            ordered_csat,
            reconciliation_cache,
            entry_coverage_cache,
        ),
        tickets,
        tuple(entry_coverage_cache.records) if entry_coverage_cache is not None else (),
    )


def ticket_page(
    snapshot: DashboardSnapshot,
    *,
    cohort_week: str | None = None,
    cohort_weeks: str | None = None,
    opened_from: str | None = None,
    opened_to: str | None = None,
    outcome: str | None = None,
    ticket_id: str | None = None,
    issue_category: str | None = None,
    app: str | None = None,
    product_code: str | None = None,
    skill: str | None = None,
    intent: str | None = None,
    tpe_code: str | None = None,
    model_core: str | None = None,
    transfer_reason: str | None = None,
    csat_satisfaction: str | None = None,
    gt4_turn: bool | None = None,
    transferred: bool | None = None,
    is_weekend_start: bool | None = None,
    week_definition: str | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, object]:
    """Return a page from the allowlisted ticket projection only.

    Dimension values are never treated as open text: every requested value is
    checked against the current safe snapshot before ticket filtering.
    """
    _validate_ticket_filters(
        cohort_week=cohort_week,
        cohort_weeks=cohort_weeks,
        opened_from=opened_from,
        opened_to=opened_to,
        ticket_id=ticket_id,
        page=page,
        page_size=page_size,
    )
    selected_cohort_weeks = _parse_cohort_weeks_filter(cohort_weeks)
    # opened_from/opened_to are calendar days in the picker's own timezone
    # (Asia/Ho_Chi_Minh, same as every other date-derived field in this module
    # -- cohort_week, is_weekend_start, ...). Bounding in UTC instead would
    # shift the window by up to 7 hours and leak into the next local day.
    opened_from_bound = (
        None if opened_from is None
        else datetime.combine(date.fromisoformat(opened_from), time.min, tzinfo=_VIETNAM_TIMEZONE)
    )
    opened_to_bound = (
        None if opened_to is None
        else datetime.combine(date.fromisoformat(opened_to), time.max, tzinfo=_VIETNAM_TIMEZONE)
    )
    # Every dimension filter except `intent` (free-text with a datalist, not a
    # closed option list) and the tri-state booleans accepts a comma-separated
    # multi-select value, same convention as `cohort_weeks`: a bare single
    # value parses identically to the old exact-match filter.
    selected_outcomes = _parse_multi_ticket_filter(outcome, frozenset(_OUTCOMES), "outcome")
    multi_strings = {
        name: _parse_multi_ticket_filter(value, _ticket_filter_allowlist(snapshot, name), name)
        for name, value in {
            "issue_category": issue_category,
            "app": app,
            "product_code": product_code,
            "skill": skill,
            "tpe_code": tpe_code,
            "model_core": model_core,
        }.items()
    }
    if intent is not None and (
        not isinstance(intent, str)
        or intent not in _ticket_filter_allowlist(snapshot, "intent")
    ):
        raise ValueError("intent is invalid")
    selected_transfer_reasons = _parse_multi_ticket_filter(
        transfer_reason, _TRANSFER_TRIGGER_REASONS, "transfer_reason"
    )
    selected_csat_states = _parse_multi_ticket_filter(
        csat_satisfaction, _CSAT_TICKET_STATES, "csat_satisfaction"
    )
    for name, value in {
        "gt4_turn": gt4_turn,
        "transferred": transferred,
        "is_weekend_start": is_weekend_start,
    }.items():
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{name} is invalid")
    if week_definition is not None and week_definition not in _VIEWS:
        raise ValueError("week_definition is invalid")
    effective_sort_direction = _validate_ticket_sort(sort_by, sort_direction)
    rows = [
        row for row in snapshot.tickets
        if (cohort_week is None or row.cohort_week == cohort_week)
        and (
            selected_cohort_weeks is None
            or row.cohort_week in selected_cohort_weeks
        )
        and (
            opened_from_bound is None
            or _parse_utc_iso(row.opened_at, "opened_at") >= opened_from_bound
        )
        and (
            opened_to_bound is None
            or _parse_utc_iso(row.opened_at, "opened_at") <= opened_to_bound
        )
        and (selected_outcomes is None or row.outcome in selected_outcomes)
        and (ticket_id is None or row.ticket_id == ticket_id)
        and (multi_strings["issue_category"] is None or _ticket_filter_value(row, "issue_category") in multi_strings["issue_category"])
        and (multi_strings["app"] is None or _ticket_filter_value(row, "app") in multi_strings["app"])
        and (multi_strings["product_code"] is None or _ticket_filter_value(row, "product_code") in multi_strings["product_code"])
        and (multi_strings["skill"] is None or _ticket_filter_value(row, "skill") in multi_strings["skill"])
        and (intent is None or _ticket_filter_value(row, "intent") == intent)
        and (multi_strings["tpe_code"] is None or _ticket_filter_value(row, "tpe_code") in multi_strings["tpe_code"])
        and (multi_strings["model_core"] is None or _ticket_filter_value(row, "model_core") in multi_strings["model_core"])
        and (selected_transfer_reasons is None or row.transfer_reason in selected_transfer_reasons)
        and (
            selected_csat_states is None
            or row.csat_satisfaction in selected_csat_states
        )
        and (gt4_turn is None or row.gt4_turn == gt4_turn)
        and (transferred is None or row.transferred == transferred)
        and (is_weekend_start is None or row.is_weekend_start == is_weekend_start)
        and (week_definition != "mon_fri" or not row.is_weekend_start)
    ]
    rows = _sort_ticket_rows(rows, sort_by, effective_sort_direction)
    start = (page - 1) * page_size
    return {
        "items": [_ticket_public_dict(row) for row in rows[start:start + page_size]],
        "page": page,
        "page_size": page_size,
        "total": len(rows),
    }


def _ticket_public_dict(row: TicketRow) -> dict[str, object]:
    """Filter a ticket row down to the Ticket Explorer's public projection.

    `TicketRow` carries day-grain diagnostic fields (`transfer_rule`,
    `transfer_source`, `transfer_stage`, `transfer_skill`, `guardrail_rules`,
    `tpe_signals`) that exist only to let day aggregates reconstruct the
    weekly transfer/TPE grain (§4.1). They must never reach the browser via
    the non-aggregate ticket page.
    """
    full = asdict(row)
    return {key: full[key] for key in _TICKET_EXPLORER_PUBLIC_KEYS}


_DAY_AGGREGATE_SEGMENT_DIMENSIONS = ("skill", "app", "issue_category")


def ticket_day_aggregate(
    snapshot: DashboardSnapshot,
    *,
    opened_from: str,
    opened_to: str,
    week_definition: str | None = None,
) -> list[dict[str, object]]:
    """Sum ticket-level rows into one entry per Vietnam-local calendar day.

    Grain is a day, not a week, so the result composes upward (callers add
    days into weeks) but never needs to be decomposed. `opened_at` is UTC;
    bucketing must happen here, in Vietnam local time, matching cohort_week
    elsewhere in this module -- cutting the opened_at string in the frontend
    would silently misclassify every ticket opened at or after 17:00 UTC.

    `week_definition="mon_fri"` excludes weekend-start tickets the same way
    `ticket_page()` does, so a caller rolling the result into mon_fri weeks
    never needs its own copy of the weekend rule.
    """
    if week_definition is not None and week_definition not in _VIEWS:
        raise ValueError("week_definition is invalid")
    parsed_from = _parsed_ticket_date(opened_from, "opened_from")
    parsed_to = _parsed_ticket_date(opened_to, "opened_to")
    if parsed_from is None or parsed_to is None:
        raise ValueError("opened_from is invalid")
    if parsed_from > parsed_to:
        raise ValueError("opened_from must not be after opened_to")
    opened_from_bound = datetime.combine(parsed_from, time.min, tzinfo=_VIETNAM_TIMEZONE)
    opened_to_bound = datetime.combine(parsed_to, time.max, tzinfo=_VIETNAM_TIMEZONE)

    buckets: dict[str, list[TicketRow]] = {}
    for row in snapshot.tickets:
        opened_at = _parse_utc_iso(row.opened_at, "opened_at")
        if opened_at < opened_from_bound or opened_at > opened_to_bound:
            continue
        if week_definition == "mon_fri" and row.is_weekend_start:
            continue
        day = opened_at.astimezone(_VIETNAM_TIMEZONE).date().isoformat()
        buckets.setdefault(day, []).append(row)

    return [
        _day_aggregate_for(day, rows)
        for day, rows in sorted(buckets.items())
    ]


def _day_aggregate_for(day: str, rows: list[TicketRow]) -> dict[str, object]:
    outcomes = {"ai_end_to_end": 0, "ai_then_cs": 0, "direct_cs": 0, "unclassified": 0}
    segments: dict[str, dict[str, dict[str, int]]] = {
        dimension: {} for dimension in _DAY_AGGREGATE_SEGMENT_DIMENSIONS
    }
    ai_first_count = 0
    transferred_count = 0
    direct_cs_count = 0
    reopen_lifetime_numerator = 0
    reopen_lifetime_denominator = 0
    gt4_turn_with_cs = 0
    gt4_turn_without_cs = 0
    resolved_first_reply_count = 0
    ai_reply_sum_ai_first = 0

    for row in rows:
        outcomes[row.outcome] = outcomes.get(row.outcome, 0) + 1
        if row.ai_first:
            ai_first_count += 1
            ai_reply_sum_ai_first += row.ai_reply_count
        if row.outcome == "ai_end_to_end" and row.ai_reply_count == 1:
            resolved_first_reply_count += 1
        if row.transferred:
            transferred_count += 1
        if row.outcome == "direct_cs":
            direct_cs_count += 1
        if row.reopen_lifetime is not None:
            reopen_lifetime_numerator += row.reopen_lifetime
            reopen_lifetime_denominator += 1
        if row.gt4_turn:
            if row.transferred:
                gt4_turn_with_cs += 1
            else:
                gt4_turn_without_cs += 1
        for dimension in _DAY_AGGREGATE_SEGMENT_DIMENSIONS:
            label = getattr(row, dimension)
            if label is None:
                continue
            bucket = segments[dimension].setdefault(
                label, {"total": 0, "ai_first": 0, "transferred": 0, "reopen": 0}
            )
            bucket["total"] += 1
            if row.ai_first:
                bucket["ai_first"] += 1
            if row.transferred:
                bucket["transferred"] += 1
            if row.reopen_lifetime:
                bucket["reopen"] += row.reopen_lifetime

    return {
        "day": day,
        "total_tickets": len(rows),
        "ai_first_count": ai_first_count,
        "transferred_count": transferred_count,
        "direct_cs_count": direct_cs_count,
        "outcomes": outcomes,
        "reopen_lifetime_numerator": reopen_lifetime_numerator,
        "reopen_lifetime_denominator": reopen_lifetime_denominator,
        "gt4_turn_with_cs": gt4_turn_with_cs,
        "gt4_turn_without_cs": gt4_turn_without_cs,
        "resolved_first_reply_count": resolved_first_reply_count,
        "ai_reply_sum_ai_first": ai_reply_sum_ai_first,
        "segments": segments,
        "transfer_reasons": _day_transfer_reasons(rows),
    }


def entry_coverage_ticket_page(
    snapshot: DashboardSnapshot,
    *,
    week_definition: str = "mon_sun",
    cohort_weeks: str | None = None,
    opened_from: str | None = None,
    opened_to: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    sort_by: str = "opened_at",
    sort_dir: str = "desc",
) -> dict[str, object]:
    """Return only the safe Freshdesk entry-coverage drill-down projection."""

    if week_definition not in _VIEWS:
        raise ValueError("week_definition is invalid")
    if status is not None and status not in _ENTRY_COVERAGE_STATUSES:
        raise ValueError("status is invalid")
    if sort_by not in {"opened_at", "ticket_id"}:
        raise ValueError("sort_by is invalid")
    # Vietnam-local opening day, inclusive at both ends -- the same window the
    # day-grain aggregate above the drill-down is built from. Without it the
    # list would show whole weeks while the counts show the picked days.
    from_day = None if opened_from is None else _day_string(opened_from, "opened_from")
    to_day = None if opened_to is None else _day_string(opened_to, "opened_to")
    if from_day is not None and to_day is not None and from_day > to_day:
        raise ValueError("opened_from is invalid")
    if sort_dir not in _TICKET_SORT_DIRECTIONS:
        raise ValueError("sort_dir is invalid")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be at least 1")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= 100
    ):
        raise ValueError("page_size must be between 1 and 100")

    view = _require_mapping(snapshot.dashboard["views"], "views")[week_definition]
    weekly = _require_mapping(view, f"views.{week_definition}")["weekly"]
    allowed_weeks = {
        item["cohort_week"] for item in weekly if isinstance(item, Mapping)
    }
    selected_weeks = _parse_entry_coverage_weeks(cohort_weeks)
    if selected_weeks is None:
        selected_weeks = frozenset(allowed_weeks)
    elif not selected_weeks.issubset(allowed_weeks):
        raise ValueError("cohort_weeks contains a week outside this view")

    rows = []
    for record in snapshot.entry_coverage_tickets:
        if record.cohort_week not in selected_weeks:
            continue
        if status is not None and record.status != status:
            continue
        opened = _parse_utc_iso(
            record.opened_at, "entry coverage opened_at"
        ).astimezone(_VIETNAM_TIMEZONE)
        if week_definition != "mon_sun" and opened.weekday() >= 5:
            continue
        day = opened.date()
        if from_day is not None and day < from_day:
            continue
        if to_day is not None and day > to_day:
            continue
        rows.append(record)
    rows.sort(
        key=(
            lambda record: (
                _parse_utc_iso(record.opened_at, "entry coverage opened_at"),
                int(record.ticket_id),
            )
            if sort_by == "opened_at"
            else int(record.ticket_id)
        ),
        reverse=sort_dir == "desc",
    )
    start = (page - 1) * page_size
    return {
        "items": [
            _entry_coverage_record_dict(record)
            for record in rows[start : start + page_size]
        ],
        "page": page,
        "page_size": page_size,
        "total": len(rows),
    }


def _parse_entry_coverage_weeks(value: str | None) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("cohort_weeks is invalid")
    values = value.split(",")
    if not 1 <= len(values) <= 52 or len(set(values)) != len(values):
        raise ValueError("cohort_weeks is invalid")
    for item in values:
        try:
            parsed = date.fromisoformat(item)
        except ValueError as error:
            raise ValueError("cohort_weeks is invalid") from error
        if parsed.isoformat() != item or parsed.weekday() != 0:
            raise ValueError("cohort_weeks must contain Mondays")
    return frozenset(values)


def _validate_ticket_sort(
    sort_by: str | None,
    sort_direction: str | None,
) -> str | None:
    if sort_by is None:
        if sort_direction is not None:
            raise ValueError("sort_direction is invalid")
        return None
    if not isinstance(sort_by, str) or sort_by not in _TICKET_EXPLORER_PUBLIC_KEYS:
        raise ValueError("sort_by is invalid")
    if sort_direction is None:
        return "asc"
    if (
        not isinstance(sort_direction, str)
        or sort_direction not in _TICKET_SORT_DIRECTIONS
    ):
        raise ValueError("sort_direction is invalid")
    return sort_direction


def _sort_ticket_rows(
    rows: list[TicketRow],
    sort_by: str | None,
    sort_direction: str | None,
) -> list[TicketRow]:
    if sort_by is None:
        return sorted(rows, key=lambda row: (row.cohort_week, row.ticket_id))

    if sort_by == "csat_satisfaction":
        rated = [
            row for row in rows
            if row.csat_satisfaction in _CSAT_SORT_RANK
        ]
        unrated = [row for row in rows if row.csat_satisfaction == "unrated"]
        unavailable = [row for row in rows if row.csat_satisfaction is None]
        return [
            *sorted(
                rated,
                key=lambda row: (
                    _CSAT_SORT_RANK[row.csat_satisfaction],
                    int(row.ticket_id),
                ),
                reverse=sort_direction == "desc",
            ),
            *sorted(unrated, key=lambda row: int(row.ticket_id)),
            *sorted(unavailable, key=lambda row: int(row.ticket_id)),
        ]

    # Ticket IDs are unique in the safe projection. Pre-sorting them makes the
    # secondary order explicit and stable for every low-cardinality column.
    by_ticket_id = sorted(rows, key=lambda row: int(row.ticket_id))
    populated = [row for row in by_ticket_id if getattr(row, sort_by) is not None]
    missing = [row for row in by_ticket_id if getattr(row, sort_by) is None]
    return [
        *sorted(
            populated,
            key=lambda row: _ticket_sort_value(row, sort_by),
            reverse=sort_direction == "desc",
        ),
        # Missing values remain last in both directions so changing direction
        # never makes an absent analytical dimension look like a top result.
        *missing,
    ]


def _ticket_sort_value(
    ticket: TicketRow,
    name: str,
) -> tuple[tuple[int, int | str], ...]:
    value = getattr(ticket, name)
    if name == "ticket_id":
        return ((0, int(value)),)
    if name == "opened_at" and isinstance(value, str):
        opened_at = _parse_utc_iso(value, "opened_at")
        return ((0, int(opened_at.timestamp() * 1_000_000)),)
    if (
        name == "tpe_code"
        and isinstance(value, str)
        and _TPE_CODE_PATTERN.fullmatch(value)
    ):
        return ((0, int(value)),)
    if isinstance(value, (bool, int)):
        return ((0, int(value)),)

    normalised = normalize("NFKC", str(value)).casefold()
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _NATURAL_SORT_PART.split(normalised)
        if part
    )


def _ticket_filter_value(ticket: TicketRow, name: str) -> str:
    value = getattr(ticket, name)
    if value is not None:
        return value
    # A ticket-row skill of None means "not exactly one recorded skill" — most
    # often zero. The Explorer's skill filter options come from the segment
    # bucket labels, so this fallback must match the label those options use.
    return _NO_SKILL if name == "skill" else _MISSING


def _ticket_filter_allowlist(
    snapshot: DashboardSnapshot,
    name: str,
) -> frozenset[str]:
    """Union safe Ticket Explorer values with already-visible aggregates.

    Non-numeric session IDs are intentionally omitted from ``snapshot.tickets``
    but still contribute to the dashboard aggregates.  Their segment labels are
    therefore valid filter options even when the resulting safe ticket page is
    empty.  Intent labels come only from the schema-validated intent segment;
    they are never accepted through an open pattern or another dimension.
    """
    segment_name = "tpe" if name == "tpe_code" else name
    allowed = {
        _ticket_filter_value(ticket, name)
        for ticket in snapshot.tickets
    }
    views = _require_mapping(snapshot.dashboard["views"], "views")
    for view_name in _VIEWS:
        view = _require_mapping(views[view_name], f"views.{view_name}")
        segments = _require_mapping(
            view["segments"],
            f"views.{view_name}.segments",
        )
        buckets = _require_mapping(
            segments[segment_name],
            f"views.{view_name}.segments.{segment_name}",
        )
        allowed.update(
            label
            for label in buckets
            if isinstance(label, str)
        )
    return frozenset(allowed)


def _dashboard_payload(
    run: ReportRun,
    generated_at: datetime,
    safe_intents: Mapping[str, str | None],
    csat_cache: CSATCache | None,
    ordered_csat: Mapping[str, tuple[CachedCSATResponse, ...]],
    reconciliation_cache: ReconciliationCache | None,
    entry_coverage_cache: EntryCoverageCache | None,
) -> dict[str, object]:
    result = run.result
    selection = result.selection
    mon_sun = result.weekly_mon_sun or result.weekly
    mon_fri = result.weekly_mon_fri or tuple(
        summary for summary in mon_sun if summary.week_definition == "mon_fri"
    )
    tpe_status_index = build_tpe_status_index(result.sessions, run.taxonomy)
    views = {
        "mon_sun": _view_payload(
            result.sessions,
            mon_sun,
            "mon_sun",
            safe_intents,
            run.reopen_shadow,
            summarize_same_period(result, "mon_sun"),
            csat_cache,
            ordered_csat,
            reconciliation_cache,
            entry_coverage_cache,
            tpe_status_index,
        ),
        "mon_fri": _view_payload(
            result.sessions,
            mon_fri,
            "mon_fri",
            safe_intents,
            run.reopen_shadow,
            summarize_same_period(result, "mon_fri"),
            csat_cache,
            ordered_csat,
            reconciliation_cache,
            entry_coverage_cache,
            tpe_status_index,
        ),
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
    same_period: SamePeriodComparison | None,
    csat_cache: CSATCache | None,
    ordered_csat: Mapping[str, tuple[CachedCSATResponse, ...]],
    reconciliation_cache: ReconciliationCache | None,
    entry_coverage_cache: EntryCoverageCache | None,
    tpe_status_index: Mapping[tuple[str, str | None], str],
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
    gt4_with = sum(session.turn_count > 3 and session.transferred for session in sessions)
    gt4_without = sum(session.turn_count > 3 and not session.transferred for session in sessions)
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
                same_period,
                csat_cache,
                ordered_csat,
                reconciliation_cache,
                entry_coverage_cache,
                tpe_status_index,
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
        "transfer_reasons": _transfer_reasons(sessions, tpe_status_index),
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
                    ),
                    tpe_status_index,
                ),
            }
            for summary in weekly
        },
        "same_period": _same_period_payload(same_period),
        "csat": _csat_payload(sessions, weekly, csat_cache, ordered_csat),
        "outcome_reconciliation": _outcome_reconciliation_payload(
            sessions,
            weekly,
            reconciliation_cache,
        ),
        "entry_coverage": _entry_coverage_payload(
            weekly,
            week_definition,
            entry_coverage_cache,
        ),
        "rule_gt4": {
            "gt4_turn_total": gt4_with + gt4_without,
            "gt4_turn_with_cs": gt4_with,
            "gt4_turn_without_cs": gt4_without,
            "max_replies_rule_fired": max_replies,
        },
    }


def _outcome_reconciliation_payload(
    sessions: tuple[SessionMetrics, ...],
    weekly: tuple[WeeklySummary, ...],
    cache: ReconciliationCache | None,
) -> dict[str, object] | None:
    """Project only aggregate Freshdesk evidence for Langfuse AI-only tickets."""

    if cache is None or cache.fetched_at is None:
        return None
    records = {record.ticket_id: record for record in cache.records}
    fetched_weeks = frozenset(cache.fetched_weeks)
    by_week: dict[str, object] = {}
    for summary in weekly:
        cohort_week = summary.cohort_week.isoformat()
        if cohort_week not in fetched_weeks:
            continue
        population = tuple(
            session
            for session in sessions
            if (
                session.cohort_week == summary.cohort_week
                and _outcome(session.outcome) == "ai_end_to_end"
                and _is_safe_ticket_id(session.session_id)
            )
        )
        matched = tuple(
            records[session.session_id]
            for session in population
            if (
                session.session_id in records
                and records[session.session_id].cohort_week == cohort_week
            )
        )
        checked = sum(
            record.human_replied_after_ai is not None for record in matched
        )
        human_replied = sum(
            record.human_replied_after_ai is True for record in matched
        )
        unresolved = sum(
            record.human_replied_after_ai is None for record in matched
        )
        by_week[cohort_week] = {
            "langfuse_ai_end_to_end": len(population),
            "checked_ticket_count": checked,
            "human_replied_after_ai": human_replied,
            "unresolved_ticket_count": unresolved,
            "mismatch_rate": human_replied / checked if checked else None,
        }
    return {
        "source": "freshdesk",
        "fetched_at": cache.fetched_at,
        "by_week": by_week,
    }


def _entry_coverage_payload(
    weekly: tuple[WeeklySummary, ...],
    week_definition: str,
    cache: EntryCoverageCache | None,
) -> dict[str, object] | None:
    """Bucket Freshdesk entry coverage at both week and day grain.

    Every record carries its own `opened_at`, so the weekly shape was a
    reporting choice, not a property of the source. What the weekly *fetch*
    genuinely constrains is completeness -- a week never inventoried has no
    records at all -- and that survives as the `fetched_weeks` gate below,
    applied once and inherited by both grains.

    `by_day` keys on the ticket's Vietnam-local opening day, the same cohort
    key `ticket_day_aggregate()` uses, so a day range scopes coverage exactly
    like every other metric instead of widening to the weeks it touches.
    """
    if cache is None or cache.fetched_at is None:
        return None
    fetched_weeks = frozenset(cache.fetched_weeks)
    observed_weeks = {
        summary.cohort_week.isoformat()
        for summary in weekly
        if summary.cohort_week.isoformat() in fetched_weeks
    }
    week_members: dict[str, list[EntryCoverageRecord]] = {
        cohort_week: [] for cohort_week in observed_weeks
    }
    day_members: dict[str, list[EntryCoverageRecord]] = {}
    for record in cache.records:
        if record.cohort_week not in observed_weeks:
            continue
        opened = _parse_utc_iso(
            record.opened_at, "entry coverage opened_at"
        ).astimezone(_VIETNAM_TIMEZONE)
        if week_definition != "mon_sun" and opened.weekday() >= 5:
            continue
        week_members[record.cohort_week].append(record)
        day_members.setdefault(opened.date().isoformat(), []).append(record)
    return {
        "source": "freshdesk",
        "source_start_week": ENTRY_COVERAGE_START_WEEK,
        "fetched_at": cache.fetched_at,
        "by_week": {
            key: _entry_coverage_bucket(members)
            for key, members in sorted(week_members.items())
        },
        "by_day": {
            key: _entry_coverage_bucket(members)
            for key, members in sorted(day_members.items())
        },
    }


def _entry_coverage_bucket(
    records: Sequence[EntryCoverageRecord],
) -> dict[str, object]:
    """Aggregate one bucket of records, whatever key selected them.

    Grain-agnostic on purpose: a day bucket and a week bucket are the same
    computation over a different member list, so the two can never drift.
    """
    counts = Counter(record.status for record in records)
    return {
        "freshdesk_ticket_count": len(records),
        "ai_replied_only": counts["ai_replied_only"],
        "ai_replied_then_transferred": counts["ai_replied_then_transferred"],
        "transferred_without_ai_reply": counts["transferred_without_ai_reply"],
        "invoked_no_result": counts["invoked_no_result"],
        "not_observed_invoked": counts["not_observed_invoked"],
        "not_observed_human_replied": sum(
            record.status == "not_observed_invoked" and record.human_replied is True
            for record in records
        ),
        "not_observed_no_human_reply": sum(
            record.status == "not_observed_invoked" and record.human_replied is False
            for record in records
        ),
        "unresolved": counts["unresolved"],
    }


def _csat_payload(
    sessions: tuple[SessionMetrics, ...],
    weekly: tuple[WeeklySummary, ...],
    cache: CSATCache | None,
    ordered_responses: Mapping[str, tuple[CachedCSATResponse, ...]],
) -> dict[str, object] | None:
    """Bucket bot CSAT at both week and day grain.

    Freshdesk is *fetched* one week at a time, but every response it returns
    carries its own ticket, and every ticket carries its own opening instant.
    Nothing about the source forces a weekly report grain -- only the fetch
    unit is weekly, and that survives here as the completeness gate below
    (`observed_weeks`), not as the reporting grain.

    `by_day` therefore keys on the ticket's Vietnam-local opening day, the
    same cohort key `ticket_day_aggregate()` uses, so a day range scopes CSAT
    exactly like every other metric on the dashboard instead of widening to
    the full weeks it happens to touch.
    """
    if cache is None or cache.fetched_at is None:
        return None
    fetched_weeks = frozenset(cache.fetched_weeks)
    observed_weeks = {
        summary.cohort_week
        for summary in weekly
        if summary.cohort_week.isoformat() in fetched_weeks
    }
    # A week Freshdesk was never asked about has no responses at all. Letting
    # its tickets into a bucket would read as "nobody rated us" rather than
    # "we have not looked", so they are excluded at both grains.
    scoped = tuple(
        session
        for session in sessions
        if _is_safe_ticket_id(session.session_id)
        and session.cohort_week in observed_weeks
    )
    week_members: dict[str, list[SessionMetrics]] = {
        summary.cohort_week.isoformat(): []
        for summary in weekly
        if summary.cohort_week in observed_weeks
    }
    day_members: dict[str, list[SessionMetrics]] = {}
    for session in scoped:
        week_members[session.cohort_week.isoformat()].append(session)
        day = (
            session.turn0_timestamp.astimezone(_VIETNAM_TIMEZONE).date().isoformat()
        )
        day_members.setdefault(day, []).append(session)
    return {
        "source": "freshdesk",
        "fetched_at": cache.fetched_at,
        "by_week": {
            key: _csat_bucket(members, ordered_responses)
            for key, members in sorted(week_members.items())
        },
        "by_day": {
            key: _csat_bucket(members, ordered_responses)
            for key, members in sorted(day_members.items())
        },
    }


def _csat_bucket(
    sessions: Sequence[SessionMetrics],
    ordered_responses: Mapping[str, tuple[CachedCSATResponse, ...]],
) -> dict[str, object]:
    """Aggregate one bucket of tickets, whatever key selected them.

    Grain-agnostic on purpose: a day bucket and a week bucket are the same
    computation over a different member list, so the two can never drift.
    """
    session_by_ticket = {session.session_id: session for session in sessions}
    ticket_responses = {
        ticket_id: ordered_responses[ticket_id]
        for ticket_id in sorted(session_by_ticket)
        if ticket_id in ordered_responses
    }
    latest = {
        ticket_id: responses[-1]
        for ticket_id, responses in ticket_responses.items()
        if responses
    }
    buckets = Counter(
        response.satisfaction_bucket for response in latest.values()
    )
    outcome_counts = {
        outcome: _empty_csat_counts()
        for outcome in _OUTCOMES
    }
    response_outcome_counts = {
        outcome: _empty_csat_counts()
        for outcome in _OUTCOMES
    }
    dimension_counts: dict[str, dict[str, dict[str, int]]] = {
        "skill": {},
        "issue_category": {},
    }
    response_dimension_counts: dict[str, dict[str, dict[str, int]]] = {
        "skill": {},
        "issue_category": {},
    }
    for ticket_id, response in latest.items():
        session = session_by_ticket[ticket_id]
        outcome = _outcome(session.outcome)
        _increment_csat_counts(outcome_counts[outcome], response)
        dimension_values = {
            "skill": _skill_bucket(session),
            "issue_category": _safe_dimension(
                session.dimensions.issue_category
            ),
        }
        for dimension, value in dimension_values.items():
            counts = dimension_counts[dimension].setdefault(
                value,
                _empty_csat_counts(),
            )
            _increment_csat_counts(counts, response)
    for ticket_id, responses in ticket_responses.items():
        session = session_by_ticket[ticket_id]
        outcome = _outcome(session.outcome)
        dimension_values = {
            "skill": _skill_bucket(session),
            "issue_category": _safe_dimension(
                session.dimensions.issue_category
            ),
        }
        for response in responses:
            _increment_csat_counts(response_outcome_counts[outcome], response)
            for dimension, value in dimension_values.items():
                counts = response_dimension_counts[dimension].setdefault(
                    value,
                    _empty_csat_counts(),
                )
                _increment_csat_counts(counts, response)

    feedback_entries: list[dict[str, object]] = []
    for ticket_id, responses in ticket_responses.items():
        session = session_by_ticket[ticket_id]
        response_total = len(responses)
        for response_number, response in enumerate(responses, start=1):
            if response.comment_redacted is None:
                continue
            feedback_entries.append(
                {
                    "ticket_id": ticket_id,
                    "responded_at": response.responded_at,
                    "satisfaction_bucket": response.satisfaction_bucket,
                    "outcome": _outcome(session.outcome),
                    "skill": _skill_bucket(session),
                    "issue_category": _safe_dimension(
                        session.dimensions.issue_category
                    ),
                    "text": response.comment_redacted,
                    "response_number": response_number,
                    "response_total": response_total,
                    "is_latest_for_ticket": response_number == response_total,
                }
            )
    feedback_entries.sort(
        key=lambda item: (
            _parse_utc_iso(item["responded_at"], "CSAT responded_at"),
            item["ticket_id"],
            item["response_number"],
        )
    )
    response_count = sum(len(responses) for responses in ticket_responses.values())
    return {
        "response_count": response_count,
        "ticket_count": len(latest),
        "positive": buckets["positive"],
        "neutral": buckets["neutral"],
        "negative": buckets["negative"],
        "by_outcome": outcome_counts,
        "by_dimension": {
            dimension: [
                {"value": value, **counts}
                for value, counts in sorted(
                    values.items(),
                    key=lambda item: (
                        -item[1]["ticket_count"],
                        _natural_string_sort_key(item[0]),
                    ),
                )
            ]
            for dimension, values in dimension_counts.items()
        },
        "response_by_outcome": response_outcome_counts,
        "response_by_dimension": {
            dimension: [
                {"value": value, **counts}
                for value, counts in sorted(
                    values.items(),
                    key=lambda item: (
                        -item[1]["ticket_count"],
                        _natural_string_sort_key(item[0]),
                    ),
                )
            ]
            for dimension, values in response_dimension_counts.items()
        },
        "feedback_entries": feedback_entries,
    }


def _csat_response_order(
    response: CachedCSATResponse,
) -> tuple[datetime, str]:
    return (
        _parse_utc_iso(response.responded_at, "CSAT responded_at"),
        response.response_key,
    )


def _ordered_csat_by_ticket(
    responses: tuple[CachedCSATResponse, ...],
) -> dict[str, tuple[CachedCSATResponse, ...]]:
    grouped: dict[str, list[CachedCSATResponse]] = defaultdict(list)
    for response in responses:
        grouped[response.ticket_id].append(response)
    return {
        ticket_id: tuple(sorted(items, key=_csat_response_order))
        for ticket_id, items in sorted(grouped.items())
    }


def _empty_csat_counts() -> dict[str, int]:
    return {
        "ticket_count": 0,
        "positive": 0,
        "neutral": 0,
        "negative": 0,
    }


def _increment_csat_counts(
    counts: dict[str, int],
    response: CachedCSATResponse,
) -> None:
    counts["ticket_count"] += 1
    counts[response.satisfaction_bucket] += 1


def _natural_string_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    normalised = normalize("NFKC", value).casefold()
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _NATURAL_SORT_PART.split(normalised)
        if part
    )


def _same_period_payload(
    same_period: SamePeriodComparison | None,
) -> dict[str, object] | None:
    if same_period is None:
        return None
    return {
        "cutoff_date": same_period.cutoff_date.isoformat(),
        "cutoff_weekday": same_period.cutoff_weekday,
        "current": _same_period_week_payload(same_period.current),
        "baseline": {
            "weeks_used": same_period.baseline.weeks_used,
            "ai_first_rate": same_period.baseline.ai_first_rate,
            "reopen_lifetime_rate": same_period.baseline.reopen_lifetime_rate,
        },
        "by_week": {
            week.isoformat(): _same_period_week_payload(summary)
            for week, summary in same_period.by_week.items()
        },
    }


def _same_period_week_payload(summary: WeeklySummary) -> dict[str, object]:
    return {
        "cohort_week": summary.cohort_week.isoformat(),
        "total_tickets": summary.total_tickets,
        "ai_first_count": summary.ai_first_count,
        "ai_first_rate": summary.ai_first_rate,
        "reopen_lifetime_rate": summary.reopen_lifetime_rate,
        "reopen_lifetime_numerator": summary.reopen_lifetime_numerator,
        "reopen_lifetime_denominator": summary.reopen_lifetime_denominator,
    }


def _valid_tpe_signals(
    values: object,
) -> tuple[tuple[str, str | None], ...]:
    if not isinstance(values, tuple):
        return ()
    parsed: set[tuple[str, str | None]] = set()
    for value in values:
        if not isinstance(value, tuple) or len(value) != 2:
            continue
        transstatus, raw_step_result = value
        if (
            not isinstance(transstatus, str)
            or _TPE_CODE_PATTERN.fullmatch(transstatus) is None
        ):
            continue
        step_result = (
            raw_step_result
            if isinstance(raw_step_result, str)
            and _TPE_CODE_PATTERN.fullmatch(raw_step_result) is not None
            else None
        )
        parsed.add((transstatus, step_result))
    return tuple(
        sorted(
            parsed,
            key=lambda item: (
                item[0],
                item[1] is None,
                item[1] or "",
            ),
        )
    )


def _unique_tpe_transstatus(values: object) -> str | None:
    transstatuses = {
        transstatus
        for transstatus, _step_result in _valid_tpe_signals(values)
    }
    return next(iter(transstatuses)) if len(transstatuses) == 1 else None


def _tpe_rows_from_signals(
    tpe_counts: Mapping[tuple[str, str | None], int],
    tpe_status_index: Mapping[tuple[str, str | None], str],
) -> list[dict[str, object]]:
    return [
        {
            "transstatus": transstatus,
            "step_result": step_result,
            "count": count,
            # None = cap chua co trong taxonomy.  Browser hien "chua phan loai";
            # khong bao gio suy dien nghia tu con so.
            "status": tpe_status_index.get((transstatus, step_result)),
        }
        for (transstatus, step_result), count in sorted(
            tpe_counts.items(),
            key=lambda item: (
                -item[1],
                item[0][0],
                item[0][1] is None,
                item[0][1] or "",
            ),
        )
    ]


def _shape_transfer_reasons(
    *,
    denominator: int,
    trigger_counts: Counter[
        tuple[str, str | None, str | None, str | None, str | None]
    ],
    tpe_rows: list[dict[str, object]],
    guardrail_counts: Counter[str],
    escalation_blocked: int,
    step_result_missing: int,
) -> dict[str, object]:
    """Shapes the `TransferReasonsSchema`-equivalent payload from pre-counted
    totals.

    Shared by the weekly aggregator (`_transfer_reasons`, counting from
    `SessionMetrics`) and the day-grain aggregator (`_day_transfer_reasons`,
    counting from `TicketRow`) so the two never drift apart on row shape or
    sort order -- only how each counts its own source rows differs.
    """
    guardrail_rows = [
        {"rule": rule, "count": count}
        for rule, count in sorted(
            guardrail_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    trigger_rows = [
        {
            "reason": reason,
            "rule": rule,
            "source": source,
            "stage": stage,
            "skill": skill,
            "count": count,
        }
        for (reason, rule, source, stage, skill), count in sorted(
            trigger_counts.items(),
            key=lambda item: (
                -item[1],
                item[0][0],
                item[0][1] or "",
                item[0][2] or "",
                item[0][3] or "",
                item[0][4] or "",
            ),
        )
    ]
    return {
        "observed_transfer_denominator": denominator,
        "triggers": trigger_rows,
        "tpe": tpe_rows,
        "step_result_missing": {
            "count": step_result_missing,
            "denominator": denominator,
        },
        "guardrail": guardrail_rows,
        "escalation_guard_blocked": {
            "count": escalation_blocked,
            "denominator": denominator,
        },
    }


def _transfer_reasons(
    sessions: tuple[SessionMetrics, ...],
    tpe_status_index: Mapping[tuple[str, str | None], str],
) -> dict[str, object]:
    transferred = tuple(session for session in sessions if session.transferred)
    tpe_counts: Counter[tuple[str, str | None]] = Counter()
    guardrail_counts: Counter[str] = Counter()
    trigger_counts: Counter[
        tuple[str, str | None, str | None, str | None, str | None]
    ] = Counter()
    escalation_blocked = 0
    step_result_missing = 0
    for session in transferred:
        dims = session.dimensions
        signals = _valid_tpe_signals(dims.tpe_signals)
        tpe_counts.update(signals)
        step_result_missing += int(
            not any(step_result is not None for _, step_result in signals)
        )
        # These are overlapping diagnostic indicators, not a partition of
        # transferred sessions.  Their sum may exceed the denominator and a
        # "missing reason" must never be inferred by subtraction.
        for rule in set(session.guardrail_rules):
            if rule in _GUARDRAIL_RULES:
                guardrail_counts[rule] += 1
        escalation_blocked += int(dims.escalation_guard_blocked)
        trigger_counts[_transfer_trigger_grain(session)] += 1

    return _shape_transfer_reasons(
        denominator=len(transferred),
        trigger_counts=trigger_counts,
        tpe_rows=_tpe_rows_from_signals(tpe_counts, tpe_status_index),
        guardrail_counts=guardrail_counts,
        escalation_blocked=escalation_blocked,
        step_result_missing=step_result_missing,
    )


def _day_transfer_reasons(rows: list[TicketRow]) -> dict[str, object]:
    """Day-grain equivalent of `_transfer_reasons()`, counting from stored
    `TicketRow`s instead of live `SessionMetrics`.

    `tpe_status_index` is unavailable outside generation time
    (`tpe_status.py`), so each `TicketRow.tpe_signals` entry already carries
    its resolved status, baked in by `_ticket_row()`. That per-pair status is
    a pure function of `(transstatus, step_result)`, so it is safe to rebuild
    a local index from the observed rows and hand it to the same
    `_tpe_rows_from_signals()` the weekly path uses.
    """
    transferred = [row for row in rows if row.transferred]
    tpe_counts: Counter[tuple[str, str | None]] = Counter()
    tpe_status_lookup: dict[tuple[str, str | None], str] = {}
    guardrail_counts: Counter[str] = Counter()
    trigger_counts: Counter[
        tuple[str, str | None, str | None, str | None, str | None]
    ] = Counter()
    escalation_blocked = 0
    step_result_missing = 0
    for row in transferred:
        signals = row.tpe_signals
        for transstatus, step_result, status in signals:
            tpe_counts[(transstatus, step_result)] += 1
            if status is not None:
                tpe_status_lookup[(transstatus, step_result)] = status
        step_result_missing += int(
            not any(step_result is not None for _, step_result, _ in signals)
        )
        for rule in row.guardrail_rules:
            guardrail_counts[rule] += 1
        escalation_blocked += int(row.escalation_guard_blocked)
        trigger_counts[
            (
                row.transfer_reason or "unknown",
                row.transfer_rule,
                row.transfer_source,
                row.transfer_stage,
                row.transfer_skill,
            )
        ] += 1

    return _shape_transfer_reasons(
        denominator=len(transferred),
        trigger_counts=trigger_counts,
        tpe_rows=_tpe_rows_from_signals(tpe_counts, tpe_status_lookup),
        guardrail_counts=guardrail_counts,
        escalation_blocked=escalation_blocked,
        step_result_missing=step_result_missing,
    )


def _transfer_trigger_grain(
    session: SessionMetrics,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    trigger = session.transfer_trigger
    if trigger is None:
        return ("unknown", None, None, None, None)
    skill = _safe_optional(trigger.skill)
    if (
        trigger.reason not in _TRANSFER_TRIGGER_REASONS
        or trigger.reason == "unknown"
        or trigger.rule not in _GUARDRAIL_RULES
        or trigger.source not in _TRANSFER_TRIGGER_SOURCES
        or trigger.stage not in {None, "input", "output"}
        or (
            trigger.source == "skill_guardrail_checked"
            and trigger.stage not in {"input", "output"}
        )
        or (
            trigger.source != "skill_guardrail_checked"
            and (trigger.stage is not None or trigger.skill is not None)
        )
        or (trigger.skill is not None and skill is None)
        or trigger.reason
        != _expected_transfer_reason(
            trigger.rule,
            trigger.source,
            trigger.stage,
        )
    ):
        return ("unknown", None, None, None, None)
    return (
        trigger.reason,
        trigger.rule,
        trigger.source,
        trigger.stage,
        skill,
    )


def _expected_transfer_reason(
    rule: str,
    source: str,
    stage: str | None,
) -> str:
    if (
        rule == "cs_escalation"
        and source == "skill_guardrail_checked"
        and stage == "output"
    ):
        return "skill_suggested_transfer"
    if rule == "cs_escalation" and source == "output_guardrail":
        return "ai_response_requires_transfer"
    return {
        "missing_transaction_id": "missing_transaction_id",
        "max_replies_exceeded": "max_replies_exceeded",
        "off_topic": "out_of_scope",
        "off_topic_llm": "out_of_scope",
        "empty_input": "empty_message",
        "empty_message_marker": "empty_message",
        "prompt_injection": "prompt_injection",
        "prompt_injection_llm": "prompt_injection",
        "system_prompt_leak": "prompt_injection",
        "tone_check_error": "output_check_error",
    }.get(rule, "other_guardrail")


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
            bucket["reopen"] += session.reopen_lifetime or 0
        # The missing bucket is always present, making the consumer's closure
        # logic deterministic even when this run happens to have no missing
        # data. `skill` uses its own always-present "chưa ghi nhận" bucket
        # instead, since _MISSING would sit alongside it meaning nothing.
        missing_label = _NO_SKILL if dimension == "skill" else _MISSING
        buckets.setdefault(missing_label, {"total": 0, "ai_first": 0, "transferred": 0, "reopen": 0})
        result[dimension] = dict(sorted(buckets.items()))
    return result


def _segment_value(
    session: SessionMetrics,
    dimension: str,
    safe_intents: Mapping[str, str | None],
) -> str:
    dims = session.dimensions
    value: str | None
    if dimension == "skill":
        return _skill_bucket(session)
    elif dimension == "intent":
        value = safe_intents[session.session_id]
    elif dimension == "tpe":
        value = _unique_tpe_transstatus(dims.tpe_signals)
    else:
        value = getattr(dims, dimension)
    return _safe_dimension(value) if isinstance(value, str) else _MISSING


def _skill_bucket(session: SessionMetrics) -> str:
    dims = session.dimensions
    if dims.skill_count >= 2:
        return _MULTI_SKILL
    if dims.skill_count == 1 and isinstance(dims.skill, str):
        return _safe_dimension(dims.skill)
    return _NO_SKILL


def _coverage(
    sessions: tuple[SessionMetrics, ...],
    safe_intents: Mapping[str, str | None],
) -> dict[str, float]:
    if not sessions:
        return {name: 0.0 for name in ("issue_category", "app", "tpe", "intent", "skill")}
    return {
        "issue_category": sum(_segment_value(s, "issue_category", safe_intents) != _MISSING for s in sessions) / len(sessions),
        "app": sum(_segment_value(s, "app", safe_intents) != _MISSING for s in sessions) / len(sessions),
        "tpe": sum(
            bool(_valid_tpe_signals(s.dimensions.tpe_signals))
            for s in sessions
        )
        / len(sessions),
        "intent": sum(safe_intents[s.session_id] is not None for s in sessions) / len(sessions),
        # `skill_count > 0` covers both the one-skill and multi-skill case;
        # `skill is not None` alone undercounted multi-skill tickets as
        # unrecorded even though they carry the most skill signal of any row.
        "skill": sum(s.dimensions.skill_count > 0 for s in sessions) / len(sessions),
    }


def _unmapped_tpe_codes(sessions: tuple[SessionMetrics, ...]) -> list[dict[str, object]]:
    # Kept as an empty compatibility field for one storage release. Public
    # diagnostics no longer interpret exact source signals through taxonomy.
    return []


def _data_range(weekly: tuple[WeeklySummary, ...]) -> dict[str, object]:
    with_data = [summary.cohort_week.isoformat() for summary in weekly if summary.has_data]
    return {
        "first_week_with_data": min(with_data) if with_data else None,
        "weeks_without_data": [summary.cohort_week.isoformat() for summary in weekly if not summary.has_data],
    }


def _ticket_row(
    session: SessionMetrics,
    safe_intent: str | None,
    csat_cache: CSATCache | None,
    ordered_csat: Mapping[str, tuple[CachedCSATResponse, ...]],
    tpe_status_index: Mapping[tuple[str, str | None], str],
) -> TicketRow:
    dims = session.dimensions
    cohort_week = session.cohort_week.isoformat()
    if csat_cache is None or cohort_week not in csat_cache.fetched_weeks:
        csat_satisfaction = None
    elif session.session_id not in ordered_csat:
        csat_satisfaction = "unrated"
    else:
        csat_satisfaction = ordered_csat[session.session_id][
            -1
        ].satisfaction_bucket
    trigger_grain = _transfer_trigger_grain(session) if session.transferred else None
    return TicketRow(
        ticket_id=session.session_id, opened_at=_utc_iso(session.turn0_timestamp),
        cohort_week=cohort_week, cohort_status=session.cohort_status,
        is_weekend_start=session.is_weekend_start, outcome=_outcome(session.outcome), ai_first=session.ai_first,
        transferred=session.transferred, reopen_lifetime=session.reopen_lifetime,
        reopen_within_7d=session.reopen_within_7d, ai_reply_count=session.ai_reply_count,
        turn_count=session.turn_count, gt4_turn=session.turn_count > 3,
        issue_category=_safe_dimension(dims.issue_category), app=_safe_dimension(dims.app),
        product_code=_safe_dimension(dims.product_code), skill=_skill_bucket(session),
        intent=safe_intent,
        tpe_code=_unique_tpe_transstatus(dims.tpe_signals),
        tpe_status=None,
        guardrail_rule=_safe_optional(dims.guardrail_rule),
        transfer_reason=trigger_grain[0] if trigger_grain is not None else None,
        escalation_guard_blocked=dims.escalation_guard_blocked,
        csat_satisfaction=csat_satisfaction,
        data_quality=_quality_label(session.data_quality),
        model_core=_safe_optional(dims.model_core),
        transfer_rule=trigger_grain[1] if trigger_grain is not None else None,
        transfer_source=trigger_grain[2] if trigger_grain is not None else None,
        transfer_stage=trigger_grain[3] if trigger_grain is not None else None,
        transfer_skill=trigger_grain[4] if trigger_grain is not None else None,
        guardrail_rules=tuple(sorted(set(session.guardrail_rules) & _GUARDRAIL_RULES)),
        tpe_signals=tuple(
            (transstatus, step_result, tpe_status_index.get((transstatus, step_result)))
            for transstatus, step_result in _valid_tpe_signals(dims.tpe_signals)
        ),
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
        "ai_reply_sum_ai_first": summary.ai_reply_sum_ai_first,
        "ai_reply_mean_ai_first": summary.ai_reply_mean_ai_first,
        "ai_reply_p50": summary.ai_reply_p50, "ai_reply_p90": summary.ai_reply_p90,
        "ai_reply_max": summary.ai_reply_max, "gt4_turn_with_cs": summary.gt4_turn_with_cs,
        "gt4_turn_without_cs": summary.gt4_turn_without_cs,
        "max_replies_rule_fired": summary.max_replies_rule_fired, "as_of": _utc_iso(summary.as_of),
        "resolved_first_reply": summary.resolved_first_reply,
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


def _parse_cohort_weeks_filter(value: str | None) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("cohort_weeks is invalid")
    weeks = value.split(",")
    if not 2 <= len(weeks) <= 52 or len(set(weeks)) != len(weeks):
        raise ValueError("cohort_weeks is invalid")
    for cohort_week in weeks:
        try:
            parsed = date.fromisoformat(cohort_week)
        except ValueError as error:
            raise ValueError("cohort_weeks is invalid") from error
        if parsed.weekday() != 0:
            raise ValueError("cohort_weeks must contain Mondays")
    return frozenset(weeks)


def _validate_ticket_filters(
    *,
    cohort_week: str | None,
    ticket_id: str | None,
    page: int,
    page_size: int,
    cohort_weeks: str | None = None,
    opened_from: str | None = None,
    opened_to: str | None = None,
) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be at least 1")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if ticket_id is not None and not _is_safe_ticket_id(ticket_id):
        raise ValueError("ticket_id is invalid")
    if cohort_week is not None and cohort_weeks is not None:
        raise ValueError("cohort_weeks cannot be combined with cohort_week")
    if cohort_week is not None:
        if not isinstance(cohort_week, str):
            raise ValueError("cohort_week is invalid")
        try:
            parsed = date.fromisoformat(cohort_week)
        except ValueError as error:
            raise ValueError("cohort_week is invalid") from error
        if parsed.weekday() != 0:
            raise ValueError("cohort_week must be a Monday")
    _parse_cohort_weeks_filter(cohort_weeks)
    if (opened_from is not None or opened_to is not None) and (
        cohort_week is not None or cohort_weeks is not None
    ):
        raise ValueError("opened_from cannot be combined with cohort_week")
    parsed_opened_from = _parsed_ticket_date(opened_from, "opened_from")
    parsed_opened_to = _parsed_ticket_date(opened_to, "opened_to")
    if (
        parsed_opened_from is not None
        and parsed_opened_to is not None
        and parsed_opened_from > parsed_opened_to
    ):
        raise ValueError("opened_from must not be after opened_to")


def _parse_multi_ticket_filter(
    value: str | None,
    allowed: frozenset[str],
    name: str,
) -> frozenset[str] | None:
    """Comma-separated multi-select value, same convention as ``cohort_weeks``.

    A bare single value (no comma) parses identically to the old exact-match
    filter, so this is a superset of the previous single-select behaviour.
    """
    if value is None:
        return None
    pieces = value.split(",")
    if not pieces or len(set(pieces)) != len(pieces):
        raise ValueError(f"{name} is invalid")
    if any(piece not in allowed for piece in pieces):
        raise ValueError(f"{name} is invalid")
    return frozenset(pieces)


def _parsed_ticket_date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} is invalid") from error


def _ticket_from_storage(value: object) -> TicketRow:
    ticket = _require_mapping(value, "ticket")
    _require_exact_keys(ticket, _TICKET_KEYS, "ticket")
    fields = dict(ticket)
    # JSON has no tuple type: `guardrail_rules`/`tpe_signals` round-trip
    # through disk as lists (and nested lists for tpe_signals' 3-tuples).
    # Restore the tuple shape `TicketRow` and `_validate_ticket_values`
    # require before construction.
    guardrail_rules = fields.get("guardrail_rules")
    if isinstance(guardrail_rules, list):
        fields["guardrail_rules"] = tuple(guardrail_rules)
    tpe_signals = fields.get("tpe_signals")
    if isinstance(tpe_signals, list):
        fields["tpe_signals"] = tuple(
            tuple(signal) if isinstance(signal, list) else signal
            for signal in tpe_signals
        )
    try:
        return TicketRow(**fields)
    except TypeError as error:
        raise ValueError("stored ticket is invalid") from error


def _validated_ticket_dict(ticket: object) -> dict[str, object]:
    if not isinstance(ticket, TicketRow):
        raise ValueError("tickets must contain TicketRow values")
    _validate_ticket_values(ticket)
    return asdict(ticket)


def _entry_coverage_record_dict(record: EntryCoverageRecord) -> dict[str, object]:
    if not isinstance(record, EntryCoverageRecord):
        raise ValueError("entry coverage tickets are invalid")
    return {
        "ticket_id": record.ticket_id,
        "opened_at": record.opened_at,
        "cohort_week": record.cohort_week,
        "status": record.status,
        "human_replied": record.human_replied,
    }


def _entry_coverage_record_from_storage(value: object) -> EntryCoverageRecord:
    mapping = _require_mapping(value, "entry coverage ticket")
    _require_exact_keys(
        mapping,
        {"ticket_id", "opened_at", "cohort_week", "status", "human_replied"},
        "entry coverage ticket",
    )
    try:
        return EntryCoverageRecord(**dict(mapping))
    except (TypeError, EntryCoverageCacheError) as error:
        raise ValueError("stored entry coverage ticket is invalid") from error


def _validate_entry_coverage_records(
    records: tuple[EntryCoverageRecord, ...],
) -> None:
    try:
        EntryCoverageCache(fetched_weeks={}, records=records)
    except EntryCoverageCacheError as error:
        raise ValueError("entry coverage tickets are invalid") from error


def _validate_ticket_values(ticket: TicketRow) -> None:
    _validate_ticket_filters(cohort_week=ticket.cohort_week, ticket_id=ticket.ticket_id, page=1, page_size=1)
    _parse_utc_iso(ticket.opened_at, "opened_at")
    if ticket.cohort_status not in {"complete", "wtd"}:
        raise ValueError("cohort_status is invalid")
    if ticket.outcome not in _OUTCOMES:
        raise ValueError("outcome is invalid")
    for value, name in ((ticket.is_weekend_start, "is_weekend_start"), (ticket.ai_first, "ai_first"), (ticket.transferred, "transferred"), (ticket.gt4_turn, "gt4_turn"), (ticket.escalation_guard_blocked, "escalation_guard_blocked")):
        if not isinstance(value, bool):
            raise ValueError(f"{name} is invalid")
    _nullable_nonnegative_int(ticket.reopen_lifetime, "reopen_lifetime")
    _nullable_nonnegative_int(ticket.reopen_within_7d, "reopen_within_7d")
    if ticket.reopen_within_7d not in {None, 0, 1}:
        raise ValueError("reopen_within_7d is invalid")
    _nonnegative_int(ticket.ai_reply_count, "ai_reply_count")
    _positive_int(ticket.turn_count, "turn_count")
    if ticket.gt4_turn != (ticket.turn_count > 3):
        raise ValueError("gt4_turn is inconsistent")
    for value, name in ((ticket.issue_category, "issue_category"), (ticket.app, "app"), (ticket.product_code, "product_code")):
        _safe_string(value, name)
    for value, name in (
        (ticket.skill, "skill"),
        (ticket.guardrail_rule, "guardrail_rule"),
        (ticket.model_core, "model_core"),
    ):
        if value is not None:
            _safe_string(value, name)
    if ticket.transferred:
        if ticket.transfer_reason not in _TRANSFER_TRIGGER_REASONS:
            raise ValueError("transfer_reason is invalid for a transferred ticket")
    elif ticket.transfer_reason is not None:
        raise ValueError("transfer_reason must be null for a ticket not transferred")
    if ticket.tpe_status is not None:
        raise ValueError("tpe_status must be null")
    if ticket.intent is not None and ticket.intent != "khác" and not _is_safe_intent_label(ticket.intent):
        raise ValueError("intent is invalid")
    if ticket.tpe_code is not None and (
        not isinstance(ticket.tpe_code, str)
        or _TPE_CODE_PATTERN.fullmatch(ticket.tpe_code) is None
    ):
        raise ValueError("tpe_code is invalid")
    if (
        ticket.csat_satisfaction is not None
        and ticket.csat_satisfaction not in _CSAT_TICKET_STATES
    ):
        raise ValueError("csat_satisfaction is invalid")
    if ticket.data_quality not in _QUALITY_LABELS:
        raise ValueError("data_quality is invalid")
    if ticket.transferred:
        if ticket.transfer_rule is not None and ticket.transfer_rule not in _GUARDRAIL_RULES:
            raise ValueError("transfer_rule is invalid")
    elif ticket.transfer_rule is not None:
        raise ValueError("transfer_rule must be null for a ticket not transferred")
    for value, name in (
        (ticket.transfer_source, "transfer_source"),
        (ticket.transfer_stage, "transfer_stage"),
        (ticket.transfer_skill, "transfer_skill"),
    ):
        if value is not None:
            _safe_string(value, name)
    if not ticket.transferred and (
        ticket.transfer_source is not None
        or ticket.transfer_stage is not None
        or ticket.transfer_skill is not None
    ):
        raise ValueError("transfer diagnostic fields must be null for a ticket not transferred")
    if not isinstance(ticket.guardrail_rules, tuple) or not all(
        isinstance(rule, str) and rule in _GUARDRAIL_RULES
        for rule in ticket.guardrail_rules
    ):
        raise ValueError("guardrail_rules is invalid")
    if len(set(ticket.guardrail_rules)) != len(ticket.guardrail_rules) or list(
        ticket.guardrail_rules
    ) != sorted(ticket.guardrail_rules):
        raise ValueError("guardrail_rules must be sorted, de-duplicated")
    if not isinstance(ticket.tpe_signals, tuple):
        raise ValueError("tpe_signals is invalid")
    for signal in ticket.tpe_signals:
        if not isinstance(signal, tuple) or len(signal) != 3:
            raise ValueError("tpe_signals is invalid")
        transstatus, step_result, status = signal
        if (
            not isinstance(transstatus, str)
            or _TPE_CODE_PATTERN.fullmatch(transstatus) is None
        ):
            raise ValueError("tpe_signals is invalid")
        if step_result is not None and (
            not isinstance(step_result, str)
            or _TPE_CODE_PATTERN.fullmatch(step_result) is None
        ):
            raise ValueError("tpe_signals is invalid")
        if status is not None:
            _safe_string(status, "tpe_signals status")


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
    if not isinstance(value, list):
        raise ValueError("unmapped_tpe_codes must be a list")
    if value:
        raise ValueError("unmapped_tpe_codes must be empty")


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
            "same_period",
            "csat",
            "outcome_reconciliation",
            "entry_coverage",
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
        if name == "within_7d" and counts["numerator"] > counts["denominator"]:
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
    _validate_same_period(view["same_period"], weekly_by_key)
    _validate_csat(view["csat"], weekly_by_key)
    _validate_outcome_reconciliation(
        view["outcome_reconciliation"],
        weekly_by_key,
    )
    _validate_entry_coverage(view["entry_coverage"], weekly_by_key)
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


def _validate_entry_coverage(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    coverage = _require_mapping(value, "view.entry_coverage")
    # `by_day` arrived with day-range coverage scoping. A snapshot written
    # before that is still valid and simply carries no day grain.
    _require_exact_keys(
        coverage,
        {"source", "source_start_week", "fetched_at", "by_week"}
        | ({"by_day"} if "by_day" in coverage else set()),
        "view.entry_coverage",
    )
    if coverage["source"] != "freshdesk":
        raise ValueError("view.entry_coverage source is invalid")
    if coverage["source_start_week"] != ENTRY_COVERAGE_START_WEEK:
        raise ValueError("view.entry_coverage source start week is invalid")
    _parse_utc_iso(coverage["fetched_at"], "view.entry_coverage.fetched_at")
    by_week = _require_mapping(coverage["by_week"], "view.entry_coverage.by_week")
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view.entry_coverage contains a week outside this view")
    count_keys = {
        "freshdesk_ticket_count",
        "ai_replied_only",
        "ai_replied_then_transferred",
        "transferred_without_ai_reply",
        "invoked_no_result",
        "not_observed_invoked",
        "not_observed_human_replied",
        "not_observed_no_human_reply",
        "unresolved",
    }
    for cohort_week, raw_counts in by_week.items():
        _week_string(cohort_week, "view.entry_coverage.by_week key")
        _validate_entry_coverage_bucket(
            raw_counts,
            count_keys,
            f"view.entry_coverage.by_week.{cohort_week}",
        )
    if "by_day" not in coverage:
        return
    by_day = _require_mapping(coverage["by_day"], "view.entry_coverage.by_day")
    for day, raw_counts in by_day.items():
        parsed_day = _day_string(day, "view.entry_coverage.by_day key")
        # A day belongs to exactly one cohort week, and only weeks this view
        # observed may appear -- the same containment rule `by_week` gets,
        # applied one grain down.
        if (
            parsed_day - timedelta(days=parsed_day.weekday())
        ).isoformat() not in weekly_by_key:
            raise ValueError("view.entry_coverage contains a day outside this view")
        _validate_entry_coverage_bucket(
            raw_counts,
            count_keys,
            f"view.entry_coverage.by_day.{day}",
        )


def _validate_entry_coverage_bucket(
    raw_counts: object,
    count_keys: AbstractSet[str],
    path: str,
) -> None:
    """Validate one coverage bucket. Grain-agnostic, like `_entry_coverage_bucket()`."""
    counts = _require_mapping(raw_counts, path)
    _require_exact_keys(counts, count_keys, path)
    for key in count_keys:
        _nonnegative_int(counts[key], f"{path}.{key}")
    status_total = sum(
        counts[key]
        for key in (
            "ai_replied_only",
            "ai_replied_then_transferred",
            "transferred_without_ai_reply",
            "invoked_no_result",
            "not_observed_invoked",
            "unresolved",
        )
    )
    if counts["freshdesk_ticket_count"] != status_total:
        raise ValueError("entry coverage status counts do not reconcile")
    if counts["not_observed_invoked"] != (
        counts["not_observed_human_replied"] + counts["not_observed_no_human_reply"]
    ):
        raise ValueError("entry coverage human counts do not reconcile")


def _validate_csat(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    csat = _require_mapping(value, "view.csat")
    # `by_day` arrived with day-range CSAT scoping. A snapshot written before
    # that is still valid and simply carries no day grain.
    _require_exact_keys(
        csat,
        {"source", "fetched_at", "by_week"}
        | ({"by_day"} if "by_day" in csat else set()),
        "view.csat",
    )
    if csat["source"] != "freshdesk":
        raise ValueError("view.csat source is invalid")
    _parse_utc_iso(csat["fetched_at"], "view.csat.fetched_at")
    by_week = _require_mapping(csat["by_week"], "view.csat.by_week")
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view.csat contains a week outside this view")
    for cohort_week, raw_counts in by_week.items():
        _week_string(cohort_week, "view.csat.by_week key")
        _validate_csat_bucket(
            raw_counts,
            f"view.csat.by_week.{cohort_week}",
            weekly_by_key[cohort_week]["total_tickets"],
        )
    if "by_day" not in csat:
        return
    by_day = _require_mapping(csat["by_day"], "view.csat.by_day")
    for day, raw_counts in by_day.items():
        parsed_day = _day_string(day, "view.csat.by_day key")
        # A day belongs to exactly one cohort week, and only weeks this view
        # observed may appear -- the same containment rule `by_week` gets,
        # applied one grain down.
        cohort_week = (
            parsed_day - timedelta(days=parsed_day.weekday())
        ).isoformat()
        if cohort_week not in weekly_by_key:
            raise ValueError("view.csat contains a day outside this view")
        _validate_csat_bucket(
            raw_counts,
            f"view.csat.by_day.{day}",
            weekly_by_key[cohort_week]["total_tickets"],
        )


def _day_string(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} is invalid") from None


def _validate_csat_bucket(
    raw_counts: object,
    path: str,
    population_cap: object,
) -> None:
    """Validate one CSAT bucket. Grain-agnostic, like `_csat_bucket()`.

    `population_cap` is the ticket population the bucket may not exceed: its
    own week at week grain, and its containing week at day grain -- a day can
    never hold more rated tickets than the week it sits in.
    """
    count_keys = {"response_count", "ticket_count", *_CSAT_BUCKETS}
    counts = _require_mapping(raw_counts, path)
    _require_exact_keys(
        counts,
        count_keys
        | {
            "by_outcome",
            "by_dimension",
            "response_by_outcome",
            "response_by_dimension",
            "feedback_entries",
        },
        path,
    )
    for key in count_keys:
        _nonnegative_int(
            counts[key],
            f"{path}.{key}",
        )
    if counts["response_count"] < counts["ticket_count"]:
        raise ValueError("view.csat ticket count exceeds response count")
    if counts["ticket_count"] != sum(counts[key] for key in _CSAT_BUCKETS):
        raise ValueError("view.csat ticket counts do not reconcile")
    if counts["ticket_count"] > population_cap:
        raise ValueError("view.csat ticket count exceeds weekly population")

    by_outcome = _require_mapping(
        counts["by_outcome"],
        f"{path}.by_outcome",
    )
    _require_exact_keys(
        by_outcome,
        set(_OUTCOMES),
        f"{path}.by_outcome",
    )
    outcome_rows = [
        _validate_csat_count_row(
            by_outcome[outcome],
            f"view.csat outcome {outcome}",
        )
        for outcome in _OUTCOMES
    ]
    _validate_csat_rollup(counts, outcome_rows, "outcome")

    by_dimension = _require_mapping(
        counts["by_dimension"],
        f"{path}.by_dimension",
    )
    _require_exact_keys(
        by_dimension,
        {"skill", "issue_category"},
        f"{path}.by_dimension",
    )
    for dimension in ("skill", "issue_category"):
        raw_rows = by_dimension[dimension]
        if not isinstance(raw_rows, list):
            raise ValueError("view.csat dimension rows are invalid")
        labels: set[str] = set()
        dimension_rows: list[Mapping[str, object]] = []
        for raw_row in raw_rows:
            row = _require_mapping(raw_row, "view.csat dimension row")
            _require_exact_keys(
                row,
                {"value", "ticket_count", *_CSAT_BUCKETS},
                "view.csat dimension row",
            )
            label = _safe_string(row["value"], "view.csat dimension value")
            if label in labels:
                raise ValueError("view.csat dimension values are duplicated")
            labels.add(label)
            dimension_rows.append(
                _validate_csat_count_row(
                    {
                        key: row[key]
                        for key in ("ticket_count", *_CSAT_BUCKETS)
                    },
                    "view.csat dimension row",
                )
            )
        _validate_csat_rollup(counts, dimension_rows, "dimension")

    response_by_outcome = _require_mapping(
        counts["response_by_outcome"],
        f"{path}.response_by_outcome",
    )
    _require_exact_keys(
        response_by_outcome,
        set(_OUTCOMES),
        f"{path}.response_by_outcome",
    )
    response_outcome_rows = [
        _validate_csat_count_row(
            response_by_outcome[outcome],
            f"view.csat response outcome {outcome}",
        )
        for outcome in _OUTCOMES
    ]
    response_totals = {
        "ticket_count": counts["response_count"],
        **{
            bucket: sum(row[bucket] for row in response_outcome_rows)
            for bucket in _CSAT_BUCKETS
        },
    }
    _validate_csat_rollup(response_totals, response_outcome_rows, "response outcome")

    response_by_dimension = _require_mapping(
        counts["response_by_dimension"],
        f"{path}.response_by_dimension",
    )
    _require_exact_keys(
        response_by_dimension,
        {"skill", "issue_category"},
        f"{path}.response_by_dimension",
    )
    for dimension in ("skill", "issue_category"):
        raw_rows = response_by_dimension[dimension]
        if not isinstance(raw_rows, list):
            raise ValueError("view.csat response dimension rows are invalid")
        labels: set[str] = set()
        response_dimension_rows: list[Mapping[str, object]] = []
        for raw_row in raw_rows:
            row = _require_mapping(raw_row, "view.csat response dimension row")
            _require_exact_keys(
                row,
                {"value", "ticket_count", *_CSAT_BUCKETS},
                "view.csat response dimension row",
            )
            label = _safe_string(
                row["value"], "view.csat response dimension value"
            )
            if label in labels:
                raise ValueError(
                    "view.csat response dimension values are duplicated"
                )
            labels.add(label)
            response_dimension_rows.append(
                _validate_csat_count_row(
                    {
                        key: row[key]
                        for key in ("ticket_count", *_CSAT_BUCKETS)
                    },
                    "view.csat response dimension row",
                )
            )
        _validate_csat_rollup(
            response_totals,
            response_dimension_rows,
            "response dimension",
        )

    feedback_entries = counts["feedback_entries"]
    if (
        not isinstance(feedback_entries, list)
        or len(feedback_entries) > counts["response_count"]
    ):
        raise ValueError("view.csat feedback entries are invalid")
    ticket_metadata: dict[str, tuple[object, ...]] = {}
    ticket_numbers: dict[str, set[int]] = defaultdict(set)
    for raw_entry in feedback_entries:
        entry = _require_mapping(raw_entry, "view.csat feedback entry")
        _require_exact_keys(
            entry,
            {
                "ticket_id",
                "responded_at",
                "satisfaction_bucket",
                "outcome",
                "skill",
                "issue_category",
                "text",
                "response_number",
                "response_total",
                "is_latest_for_ticket",
            },
            "view.csat feedback entry",
        )
        if not _is_safe_ticket_id(entry["ticket_id"]):
            raise ValueError("view.csat feedback ticket_id is invalid")
        _parse_utc_iso(
            entry["responded_at"],
            "view.csat feedback responded_at",
        )
        if entry["satisfaction_bucket"] not in _CSAT_BUCKETS:
            raise ValueError("view.csat feedback bucket is invalid")
        if entry["outcome"] not in _OUTCOMES:
            raise ValueError("view.csat feedback outcome is invalid")
        skill = _safe_string(entry["skill"], "view.csat feedback skill")
        issue_category = _safe_string(
            entry["issue_category"],
            "view.csat feedback issue_category",
        )
        text = _safe_string(entry["text"], "view.csat feedback text")
        if _COMMENT_URL.search(text):
            raise ValueError("view.csat feedback text is unsafe")
        if len(text) > 200:
            raise ValueError("view.csat feedback text is invalid")
        response_number = _positive_int(
            entry["response_number"],
            "view.csat feedback response number",
        )
        response_total = _positive_int(
            entry["response_total"],
            "view.csat feedback response total",
        )
        if response_number > response_total:
            raise ValueError("view.csat feedback response number exceeds total")
        if response_total > counts["response_count"]:
            raise ValueError("view.csat feedback response total is invalid")
        if not isinstance(entry["is_latest_for_ticket"], bool):
            raise ValueError("view.csat feedback latest marker is invalid")
        if entry["is_latest_for_ticket"] != (response_number == response_total):
            raise ValueError("view.csat feedback latest marker is inconsistent")
        ticket_id = entry["ticket_id"]
        metadata = (
            response_total,
            entry["outcome"],
            skill,
            issue_category,
        )
        if ticket_id in ticket_metadata and ticket_metadata[ticket_id] != metadata:
            raise ValueError("view.csat feedback ticket metadata is inconsistent")
        if response_number in ticket_numbers[ticket_id]:
            raise ValueError("view.csat feedback response number is duplicated")
        ticket_metadata[ticket_id] = metadata
        ticket_numbers[ticket_id].add(response_number)


def _validate_outcome_reconciliation(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    reconciliation = _require_mapping(value, "view.outcome_reconciliation")
    _require_exact_keys(
        reconciliation,
        {"source", "fetched_at", "by_week"},
        "view.outcome_reconciliation",
    )
    if reconciliation["source"] != "freshdesk":
        raise ValueError("view outcome reconciliation source is invalid")
    _parse_utc_iso(
        reconciliation["fetched_at"],
        "view.outcome_reconciliation.fetched_at",
    )
    by_week = _require_mapping(
        reconciliation["by_week"],
        "view.outcome_reconciliation.by_week",
    )
    if not set(by_week).issubset(weekly_by_key):
        raise ValueError("view outcome reconciliation contains an unknown week")
    keys = {
        "langfuse_ai_end_to_end",
        "checked_ticket_count",
        "human_replied_after_ai",
        "unresolved_ticket_count",
        "mismatch_rate",
    }
    for cohort_week, raw_row in by_week.items():
        _week_string(cohort_week, "view.outcome_reconciliation.by_week key")
        row = _require_mapping(
            raw_row,
            f"view.outcome_reconciliation.by_week.{cohort_week}",
        )
        _require_exact_keys(
            row,
            keys,
            f"view.outcome_reconciliation.by_week.{cohort_week}",
        )
        for key in keys - {"mismatch_rate"}:
            _nonnegative_int(
                row[key],
                f"view outcome reconciliation {key}",
            )
        population = row["langfuse_ai_end_to_end"]
        checked = row["checked_ticket_count"]
        human_replied = row["human_replied_after_ai"]
        unresolved = row["unresolved_ticket_count"]
        if checked + unresolved > population or human_replied > checked:
            raise ValueError("view outcome reconciliation counts do not reconcile")
        mismatch_rate = row["mismatch_rate"]
        if checked == 0:
            if mismatch_rate is not None:
                raise ValueError("view outcome reconciliation rate is invalid")
        else:
            _rate(mismatch_rate, "view outcome reconciliation mismatch rate")
            if abs(mismatch_rate - human_replied / checked) > 1e-12:
                raise ValueError("view outcome reconciliation rate does not reconcile")
        weekly_ai_end_to_end = weekly_by_key[cohort_week][
            "ai_end_to_end_count"
        ]
        if population > weekly_ai_end_to_end:
            raise ValueError("view outcome reconciliation population does not reconcile")


def _validate_csat_count_row(
    value: object,
    name: str,
) -> Mapping[str, object]:
    row = _require_mapping(value, name)
    _require_exact_keys(row, {"ticket_count", *_CSAT_BUCKETS}, name)
    for key in ("ticket_count", *_CSAT_BUCKETS):
        _nonnegative_int(row[key], f"{name}.{key}")
    if row["ticket_count"] != sum(row[key] for key in _CSAT_BUCKETS):
        raise ValueError(f"{name} buckets do not reconcile")
    return row


def _validate_csat_rollup(
    totals: Mapping[str, object],
    rows: list[Mapping[str, object]],
    name: str,
) -> None:
    for key in ("ticket_count", *_CSAT_BUCKETS):
        if sum(row[key] for row in rows) != totals[key]:
            raise ValueError(f"view.csat {name} counts do not reconcile")


def _validate_same_period(
    value: object,
    weekly_by_key: Mapping[str, Mapping[str, object]],
) -> None:
    if value is None:
        return
    same_period = _require_mapping(value, "view.same_period")
    _require_exact_keys(
        same_period,
        {"cutoff_date", "cutoff_weekday", "current", "baseline", "by_week"},
        "view.same_period",
    )
    cutoff = _date_string(same_period["cutoff_date"], "view.same_period.cutoff_date")
    weekday = _positive_int(
        same_period["cutoff_weekday"],
        "view.same_period.cutoff_weekday",
    )
    if weekday > 7:
        raise ValueError("view.same_period.cutoff_weekday is invalid")
    if weekday != cutoff.isoweekday():
        raise ValueError("view.same_period cutoff weekday does not match date")
    current = _validate_same_period_week(
        same_period["current"],
        "view.same_period.current",
    )
    current_weekly = weekly_by_key.get(current["cohort_week"])
    if current_weekly is None or current_weekly["cohort_status"] != "wtd":
        raise ValueError("view.same_period.current must identify the running week")
    baseline = _require_mapping(same_period["baseline"], "view.same_period.baseline")
    _require_exact_keys(
        baseline,
        {"weeks_used", "ai_first_rate", "reopen_lifetime_rate"},
        "view.same_period.baseline",
    )
    weeks_used = _positive_int(
        baseline["weeks_used"],
        "view.same_period.baseline.weeks_used",
    )
    if weeks_used < 2:
        raise ValueError("view.same_period baseline needs at least two weeks")
    if weeks_used > 4:
        raise ValueError("view.same_period.baseline.weeks_used exceeds four")
    baseline_ai_rate = _rate(
        baseline["ai_first_rate"],
        "view.same_period.baseline.ai_first_rate",
    )
    baseline_reopen_rate = _nullable_nonnegative_ratio(
        baseline["reopen_lifetime_rate"],
        "view.same_period.baseline.reopen_lifetime_rate",
    )
    by_week = _require_mapping(same_period["by_week"], "view.same_period.by_week")
    if current["cohort_week"] not in by_week:
        raise ValueError("view.same_period.by_week must include current week")
    current_week = date.fromisoformat(current["cohort_week"])
    validated_by_week: dict[date, Mapping[str, object]] = {}
    for cohort_week, detail_value in by_week.items():
        _week_string(cohort_week, "view.same_period.by_week key")
        if cohort_week not in weekly_by_key:
            raise ValueError("view.same_period.by_week key is outside view.by_week")
        detail = _validate_same_period_week(
            detail_value,
            f"view.same_period.by_week.{cohort_week}",
        )
        if detail["cohort_week"] != cohort_week:
            raise ValueError("view.same_period by_week key does not match cohort_week")
        parsed_week = date.fromisoformat(cohort_week)
        if parsed_week > current_week:
            raise ValueError("view.same_period.by_week cannot extend past current")
        validated_by_week[parsed_week] = detail

    current_detail = validated_by_week[current_week]
    if dict(current_detail) != dict(current):
        raise ValueError("view.same_period.current must match its by_week row")

    contributors = [
        detail
        for week, detail in sorted(validated_by_week.items())
        if week < current_week and detail["total_tickets"] > 0
    ][-4:]
    if len(contributors) != weeks_used:
        raise ValueError("view.same_period.baseline.weeks_used is inconsistent")
    expected_ai_rate = sum(
        float(detail["ai_first_rate"]) for detail in contributors
    ) / weeks_used
    if abs(baseline_ai_rate - expected_ai_rate) > 1e-12:
        raise ValueError("view.same_period.baseline.ai_first_rate is inconsistent")
    contributor_reopen_rates = [
        float(detail["reopen_lifetime_rate"])
        for detail in contributors
        if detail["reopen_lifetime_rate"] is not None
    ]
    expected_reopen_rate = (
        sum(contributor_reopen_rates) / len(contributor_reopen_rates)
        if contributor_reopen_rates
        else None
    )
    if (
        (baseline_reopen_rate is None) != (expected_reopen_rate is None)
        or (
            baseline_reopen_rate is not None
            and expected_reopen_rate is not None
            and abs(baseline_reopen_rate - expected_reopen_rate) > 1e-12
        )
    ):
        raise ValueError(
            "view.same_period.baseline.reopen_lifetime_rate is inconsistent"
        )


def _validate_same_period_week(
    value: object,
    name: str,
) -> Mapping[str, object]:
    item = _require_mapping(value, name)
    _require_exact_keys(
        item,
        {
            "cohort_week",
            "total_tickets",
            "ai_first_count",
            "ai_first_rate",
            "reopen_lifetime_rate",
            "reopen_lifetime_numerator",
            "reopen_lifetime_denominator",
        },
        name,
    )
    _week_string(item["cohort_week"], f"{name}.cohort_week")
    total = _nonnegative_int(item["total_tickets"], f"{name}.total_tickets")
    ai_first = _nonnegative_int(item["ai_first_count"], f"{name}.ai_first_count")
    if ai_first > total:
        raise ValueError(f"{name}.ai_first_count exceeds total")
    ai_rate = _rate(item["ai_first_rate"], f"{name}.ai_first_rate")
    expected_ai_rate = ai_first / total if total else 0.0
    if abs(ai_rate - expected_ai_rate) > 1e-12:
        raise ValueError(f"{name}.ai_first_rate does not match division")
    reopen_numerator = _nonnegative_int(
        item["reopen_lifetime_numerator"],
        f"{name}.reopen_lifetime_numerator",
    )
    reopen_denominator = _nonnegative_int(
        item["reopen_lifetime_denominator"],
        f"{name}.reopen_lifetime_denominator",
    )
    reopen_rate = _nullable_nonnegative_ratio(
        item["reopen_lifetime_rate"],
        f"{name}.reopen_lifetime_rate",
    )
    expected_reopen_rate = (
        reopen_numerator / reopen_denominator if reopen_denominator else None
    )
    if (
        (expected_reopen_rate is None) != (reopen_rate is None)
        or (
            expected_reopen_rate is not None
            and reopen_rate is not None
            and abs(reopen_rate - expected_reopen_rate) > 1e-12
        )
    ):
        raise ValueError(f"{name}.reopen_lifetime_rate does not match division")
    return item


def _validate_transfer_reasons(
    value: object,
    segments_value: object,
) -> None:
    reasons = _require_mapping(value, "transfer_reasons")
    _require_exact_keys(
        reasons,
        {
            "observed_transfer_denominator",
            "triggers",
            "tpe",
            "step_result_missing",
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

    trigger_rows = reasons["triggers"]
    if not isinstance(trigger_rows, list):
        raise ValueError("transfer_reasons.triggers must be a list")
    seen_triggers: set[
        tuple[str, str | None, str | None, str | None, str | None]
    ] = set()
    trigger_total = 0
    for raw_row in trigger_rows:
        row = _require_mapping(raw_row, "transfer_reasons.triggers item")
        _require_exact_keys(
            row,
            {"reason", "rule", "source", "stage", "skill", "count"},
            "transfer_reasons.triggers item",
        )
        reason = row["reason"]
        rule = row["rule"]
        source = row["source"]
        stage = row["stage"]
        skill = row["skill"]
        if reason not in _TRANSFER_TRIGGER_REASONS:
            raise ValueError("transfer_reasons trigger reason is invalid")
        if reason == "unknown":
            if any(value is not None for value in (rule, source, stage, skill)):
                raise ValueError("transfer_reasons unknown trigger is invalid")
        else:
            if rule not in _GUARDRAIL_RULES:
                raise ValueError("transfer_reasons trigger rule is invalid")
            if source not in _TRANSFER_TRIGGER_SOURCES:
                raise ValueError("transfer_reasons trigger source is invalid")
            if source == "skill_guardrail_checked":
                if stage not in {"input", "output"}:
                    raise ValueError("transfer_reasons trigger stage is invalid")
            elif stage is not None or skill is not None:
                raise ValueError("transfer_reasons global trigger metadata is invalid")
            if skill is not None and (
                not isinstance(skill, str)
                or not _is_safe_intent_label(skill)
            ):
                raise ValueError("transfer_reasons trigger skill is invalid")
            if reason != _expected_transfer_reason(rule, source, stage):
                raise ValueError("transfer_reasons trigger reason does not match source")
        key = (reason, rule, source, stage, skill)
        if key in seen_triggers:
            raise ValueError("transfer_reasons trigger rows must be unique")
        seen_triggers.add(key)
        trigger_total += _positive_int(
            row["count"],
            "transfer_reasons trigger count",
        )
    if trigger_total != denominator:
        raise ValueError("transfer_reasons triggers do not partition transfers")

    tpe_rows = reasons["tpe"]
    if not isinstance(tpe_rows, list):
        raise ValueError("transfer_reasons.tpe must be a list")
    seen_tpe: set[tuple[str, str | None]] = set()
    for raw_row in tpe_rows:
        row = _require_mapping(raw_row, "transfer_reasons.tpe item")
        _require_exact_keys(
            row,
            {"transstatus", "step_result", "count", "status"},
            "transfer_reasons.tpe item",
        )
        transstatus = row["transstatus"]
        if (
            not isinstance(transstatus, str)
            or _TPE_CODE_PATTERN.fullmatch(transstatus) is None
        ):
            raise ValueError("transfer_reasons.tpe transstatus is invalid")
        step_result = row["step_result"]
        if step_result is not None:
            if (
                not isinstance(step_result, str)
                or _TPE_CODE_PATTERN.fullmatch(step_result) is None
            ):
                raise ValueError("transfer_reasons.tpe step_result is invalid")
        status = row["status"]
        # None = cap chua co trong taxonomy TPE; khac None phai la chuoi khong
        # rong theo governed status tu resolve_tpe_status().
        if status is not None and (not isinstance(status, str) or status == ""):
            raise ValueError("transfer_reasons.tpe status is invalid")
        count = _positive_int(row["count"], "transfer_reasons.tpe count")
        key = (transstatus, step_result)
        if key in seen_tpe:
            raise ValueError("transfer_reasons.tpe rows must be unique")
        seen_tpe.add(key)
        if count > denominator:
            raise ValueError("transfer_reasons.tpe exceeds denominator")

    missing = _require_mapping(
        reasons["step_result_missing"],
        "transfer_reasons.step_result_missing",
    )
    _require_exact_keys(
        missing,
        {"count", "denominator"},
        "transfer_reasons.step_result_missing",
    )
    missing_count = _nonnegative_int(
        missing["count"],
        "transfer_reasons.step_result_missing.count",
    )
    missing_denominator = _nonnegative_int(
        missing["denominator"],
        "transfer_reasons.step_result_missing.denominator",
    )
    if missing_denominator != denominator or missing_count > denominator:
        raise ValueError("transfer_reasons step_result_missing does not reconcile")

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
        ("transstatus", "step_result"),
    )
    weekly_tpe: Counter[tuple[object, ...]] = Counter()
    aggregate_triggers = row_counter(
        aggregate,
        "triggers",
        ("reason", "rule", "source", "stage", "skill"),
    )
    weekly_triggers: Counter[tuple[object, ...]] = Counter()
    aggregate_guardrail = row_counter(
        aggregate,
        "guardrail",
        ("rule",),
    )
    weekly_guardrail: Counter[tuple[object, ...]] = Counter()
    for value in weekly:
        weekly_tpe.update(
            row_counter(value, "tpe", ("transstatus", "step_result"))
        )
        weekly_guardrail.update(
            row_counter(value, "guardrail", ("rule",))
        )
        weekly_triggers.update(
            row_counter(
                value,
                "triggers",
                ("reason", "rule", "source", "stage", "skill"),
            )
        )
    if (
        aggregate_tpe != weekly_tpe
        or aggregate_guardrail != weekly_guardrail
        or aggregate_triggers != weekly_triggers
    ):
        raise ValueError("transfer reason weekly rows do not reconcile")
    aggregate_missing = _require_mapping(
        aggregate["step_result_missing"],
        "transfer_reasons.step_result_missing",
    )
    if (
        aggregate_missing["count"]
        != sum(
            _require_mapping(
                value["step_result_missing"],
                "weekly step_result_missing",
            )["count"]
            for value in weekly
        )
        or aggregate_missing["denominator"]
        != sum(
            _require_mapping(
                value["step_result_missing"],
                "weekly step_result_missing",
            )["denominator"]
            for value in weekly
        )
    ):
        raise ValueError(
            "transfer reason weekly step_result_missing does not reconcile"
        )
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
        default_label = _NO_SKILL if dimension == "skill" else _MISSING
        expected_labels = weekly_labels or {default_label}
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
        required_missing_label = _NO_SKILL if name == "skill" else _MISSING
        if required_missing_label not in buckets:
            raise ValueError("segments must include missing bucket")
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
        for field in ("total_tickets", "ai_first_count", "ai_end_to_end_count", "ai_then_cs_count", "direct_cs_count", "unclassified_count", "reopen_lifetime_numerator", "reopen_lifetime_denominator", "gt4_turn_with_cs", "gt4_turn_without_cs", "max_replies_rule_fired", "resolved_first_reply"):
            _nonnegative_int(item[field], f"weekly {field}")
        if item["has_data"] != bool(item["total_tickets"]): raise ValueError("weekly has_data does not match total")
        if item["ai_first_count"] != item["ai_end_to_end_count"] + item["ai_then_cs_count"]: raise ValueError("weekly ai_first does not reconcile")
        if item["total_tickets"] != item["ai_end_to_end_count"] + item["ai_then_cs_count"] + item["direct_cs_count"] + item["unclassified_count"]: raise ValueError("weekly outcomes do not reconcile")
        if item["resolved_first_reply"] > item["ai_end_to_end_count"]: raise ValueError("weekly resolved_first_reply exceeds ai_end_to_end_count")
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
        _nullable_nonnegative_ratio(item["reopen_lifetime_rate"], "weekly reopen_lifetime_rate")
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
        _nonnegative_int(item["ai_reply_sum_ai_first"], "weekly ai_reply_sum_ai_first")
        _nullable_nonnegative_number(item["ai_reply_mean_ai_first"], "weekly ai_reply_mean_ai_first")
        # The dashboard shows both and the reader divides one by the other, so
        # a payload where they disagree is not merely odd -- it renders a ledger
        # that does not add up.
        if item["ai_first_count"] == 0:
            if item["ai_reply_sum_ai_first"] != 0:
                raise ValueError("weekly ai_reply_sum_ai_first must be 0 without ai_first tickets")
        elif (
            item["ai_reply_mean_ai_first"] is None
            or abs(
                item["ai_reply_sum_ai_first"]
                - item["ai_reply_mean_ai_first"] * item["ai_first_count"]
            )
            > 1e-6
        ):
            raise ValueError("weekly ai_reply_sum_ai_first does not match the mean")
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


def _date_string(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} is invalid") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{name} is invalid")
    return parsed


def _validate_count_map(value: object, keys: set[str] | frozenset[str], name: str) -> None:
    mapping = _require_mapping(value, name); _require_exact_keys(mapping, keys, name)
    for count in mapping.values(): _nonnegative_int(count, name)


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value): raise ValueError(f"{name} must be an object")
    return value


def _require_exact_keys(value: Mapping[str, object], keys: set[str] | frozenset[str], name: str) -> None:
    if set(value) != set(keys): raise ValueError(f"{name} has unsupported or missing fields")


def _parse_utc_iso(value: object, name: str) -> datetime:
    if not isinstance(value, str) or _UTC_ISO.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical UTC ISO timestamp")
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


def _nonnegative_ratio(value: object, name: str) -> float:
    """A ratio that, unlike ``_rate``, is not capped at 1 -- reopen_lifetime is
    now a per-ticket count, so its mean across tickets can exceed 1.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative ratio")
    return float(value)


def _nullable_nonnegative_ratio(value: object, name: str) -> float | None:
    return None if value is None else _nonnegative_ratio(value, name)


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
