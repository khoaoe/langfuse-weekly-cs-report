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
from typing import TYPE_CHECKING, AbstractSet, Mapping, Sequence
from unicodedata import normalize
from zoneinfo import ZoneInfo

from .ai_tag_cache import AiTagCache, AiTagCacheError, AiTagRecord
from .csat_cache import CSATCache, CachedCSATResponse
from .enrichment import build_tpe_status_index
from .entry_coverage_cache import (
    ENTRY_COVERAGE_START_WEEK,
    EntryCoverageCache,
    EntryCoverageCacheError,
    EntryCoverageRecord,
)
from .dashboard_validate import (
    _day_string,
    _require_exact_keys,
    _require_mapping,
    _validate_ai_tag_records,
    _validate_dashboard,
    _validate_entry_coverage_records,
    _validate_projected_intent_frequency,
    _validate_reopen_reason,
    _validate_ticket_sort,
    _validated_ticket_dict,
)
from .dashboard_rows import (
    _AI_REVIEW_RATING_BUCKETS,
    _AI_REVIEW_RATING_SLUGS,
    _CSAT_BUCKETS,
    _CSAT_TICKET_STATES,
    _EMAIL,
    _GUARDRAIL_RULES,
    _INTENT_PATTERN,
    _MAX_TICKET_PAGE_SIZE,
    _OUTCOMES,
    _PHONE,
    _QUALITY_LABELS,
    _TICKET_ID_PATTERN,
    _TOOL_ERROR_CODE_PATTERN,
    _TPE_CODE_PATTERN,
    _TRANSFER_TRIGGER_REASONS,
    _URL,
    _UTC_ISO,
    _UUID,
    _VIETNAMESE_FAMILY_NAMES,
    _VIETNAMESE_NAME_MIDDLES,
    TicketRow,
    _AI_REVIEW_COUNT_KEYS,
    _COMMENT_URL,
    _DASHBOARD_KEYS,
    _MISSING,
    _NO_SKILL,
    _SEGMENTS,
    _TICKET_EXPLORER_PUBLIC_KEYS,
    _TICKET_KEYS,
    _TICKET_SORT_DIRECTIONS,
    _TRANSFER_TRIGGER_SOURCES,
    _VIEWS,
    _WEEKLY_KEYS,
    _expected_transfer_reason,
    _contains_long_numeric_identifier,
    _is_safe_intent_label,
    _is_safe_ticket_id,
    _looks_like_vietnamese_personal_name,
    _nonnegative_int,
    _nullable_nonnegative_int,
    _parse_cohort_weeks_filter,
    _parse_utc_iso,
    _parsed_ticket_date,
    _positive_int,
    _require_aware,
    _safe_string,
    _utc_iso,
    _validate_ticket_filters,
    _validate_ticket_values,
)
from .reconciliation_cache import ReconciliationCache
from .models import AnalysisResult, SessionMetrics, WeeklySummary
from .pipeline import SamePeriodComparison, summarize_same_period
from .reopen_shadow import ReopenReasonShadow, unavailable_shadow
from .report import ReportRun

if TYPE_CHECKING:
    from .ai_review import AIReviewRecord
    from .ai_review_cache import AIReviewCache


_STORAGE_VERSION = 31
# `<tool>:<CODE>` as produced by `enrichment.tool_error_token`. The code half
# is either an allowlisted upper-case enum or the `khac` bucket that absorbs
# anything off the allowlist -- neither can carry free text or PII.
# The tool half must start with a letter: every real tool name does, and the
# stricter form also rules out a digit run that could carry a phone number.
_NATURAL_SORT_PART = re.compile(r"([0-9]+)")
_CSAT_SORT_RANK = {"negative": 0, "neutral": 1, "positive": 2}
_ENTRY_COVERAGE_STATUSES = frozenset(
    {
        "ai_replied_only",
        "ai_replied_then_transferred",
        "transferred_without_ai_reply",
        "invoked_no_result",
    }
)
_VIETNAM_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
_HAS_VALUE = "__has_value__"
_AI_REVIEW_RATING_TICKET_STATES = frozenset({*_AI_REVIEW_RATING_SLUGS, _MISSING})
# `skill` never used _MISSING accurately: a ticket with three distinct skills
# and a ticket with zero `execute` observations both collapsed to the same
# label. These name the two real cases instead.
_MULTI_SKILL = "Nhiều skill"
# The public shape `ticket_page()` (non-aggregate) returns to the browser.
# Deliberately excludes the day-grain diagnostic fields above: they only
# exist to let day aggregates reconstruct the weekly transfer/TPE grain and
# must never reach the Ticket Explorer projection (§4.1 privacy contract).
@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: datetime
    dashboard: dict[str, object]
    tickets: tuple[TicketRow, ...]
    entry_coverage_tickets: tuple[EntryCoverageRecord, ...] = ()
    ai_tag_tickets: tuple[AiTagRecord, ...] = ()

    def dashboard_dict(self) -> dict[str, object]:
        _require_aware(self.generated_at, "generated_at")
        dashboard = deepcopy(self.dashboard)
        _validate_dashboard(dashboard, generated_at=self.generated_at)
        _validate_projected_intent_frequency(
            dashboard,
            tuple(_validated_ticket_dict(ticket) for ticket in self.tickets),
        )
        _validate_entry_coverage_records(self.entry_coverage_tickets)
        _validate_ai_tag_records(self.ai_tag_tickets)
        return dashboard

    def storage_dict(self) -> dict[str, object]:
        tickets = tuple(_validated_ticket_dict(ticket) for ticket in self.tickets)
        # One pass, not two: `dashboard_dict` already deep-copies and runs the
        # full validator (including `_validate_projected_intent_frequency` and
        # `_validate_entry_coverage_records`), so calling it twice validated
        # the same payload twice and threw the first copy away.
        dashboard = self.dashboard_dict()
        return {
            "schema_version": _STORAGE_VERSION,
            "generated_at": _utc_iso(self.generated_at),
            "dashboard": dashboard,
            "tickets": list(tickets),
            "entry_coverage_tickets": [
                _entry_coverage_record_dict(record)
                for record in self.entry_coverage_tickets
            ],
            "ai_tag_tickets": [
                _ai_tag_record_dict(record) for record in self.ai_tag_tickets
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
                "ai_tag_tickets",
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
        raw_ai_tag_tickets = storage["ai_tag_tickets"]
        if not isinstance(raw_ai_tag_tickets, list):
            raise ValueError("ai_tag_tickets must be a list")
        ai_tag_tickets = tuple(
            _ai_tag_record_from_storage(item) for item in raw_ai_tag_tickets
        )
        _validate_ai_tag_records(ai_tag_tickets)
        _validate_projected_intent_frequency(dashboard, tuple(asdict(ticket) for ticket in tickets))
        return cls(
            generated_at=generated_at,
            dashboard=deepcopy(dashboard),
            tickets=tickets,
            entry_coverage_tickets=entry_tickets,
            ai_tag_tickets=ai_tag_tickets,
        )


def project_dashboard(
    run: ReportRun,
    *,
    csat_cache: CSATCache | None = None,
    reconciliation_cache: ReconciliationCache | None = None,
    entry_coverage_cache: EntryCoverageCache | None = None,
    ai_review_cache: AIReviewCache | None = None,
    ai_tag_cache: AiTagCache | None = None,
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
    ai_review_rating_by_ticket = {
        record.ticket_id: record.rating
        for record in (ai_review_cache.records if ai_review_cache is not None else ())
    }
    tickets = tuple(sorted(
        (
            _ticket_row(
                session,
                safe_intents[session.session_id],
                csat_cache,
                ordered_csat,
                tpe_status_index,
                ai_review_rating_by_ticket,
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
            ai_review_cache,
            ai_tag_cache,
            tickets,
        ),
        tickets,
        tuple(entry_coverage_cache.records) if entry_coverage_cache is not None else (),
        tuple(ai_tag_cache.records) if ai_tag_cache is not None else (),
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
    tool_error_codes: str | None = None,
    transfer_reason: str | None = None,
    csat_satisfaction: str | None = None,
    ai_review_rating: str | None = None,
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
    selected_tool_error_codes = _parse_multi_ticket_filter(
        tool_error_codes,
        _tool_error_code_allowlist(snapshot),
        "tool_error_codes",
    )
    selected_transfer_reasons = _parse_multi_ticket_filter(
        transfer_reason, _TRANSFER_TRIGGER_REASONS, "transfer_reason"
    )
    selected_csat_states = _parse_multi_ticket_filter(
        csat_satisfaction, _CSAT_TICKET_STATES, "csat_satisfaction"
    )
    selected_ai_review_ratings = _parse_multi_ticket_filter(
        ai_review_rating, _AI_REVIEW_RATING_TICKET_STATES, "ai_review_rating"
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
        and _matches_multi_dimension(row, "issue_category", multi_strings["issue_category"])
        and _matches_multi_dimension(row, "app", multi_strings["app"])
        and _matches_multi_dimension(row, "product_code", multi_strings["product_code"])
        and _matches_multi_dimension(row, "skill", multi_strings["skill"])
        and (intent is None or _ticket_filter_value(row, "intent") == intent)
        and _matches_multi_dimension(row, "tpe_code", multi_strings["tpe_code"])
        and _matches_multi_dimension(row, "model_core", multi_strings["model_core"])
        and (
            selected_tool_error_codes is None
            or (
                bool(row.tool_error_codes)
                if selected_tool_error_codes == frozenset({_HAS_VALUE})
                else not selected_tool_error_codes.isdisjoint(row.tool_error_codes)
            )
        )
        and (selected_transfer_reasons is None or row.transfer_reason in selected_transfer_reasons)
        and (
            selected_csat_states is None
            or row.csat_satisfaction in selected_csat_states
        )
        and _matches_multi_dimension(row, "ai_review_rating", selected_ai_review_ratings)
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
                label,
                {
                    "total": 0,
                    "ai_first": 0,
                    "transferred": 0,
                    "reopen": 0,
                    "ai_end_to_end": 0,
                    "direct_cs": 0,
                },
            )
            bucket["total"] += 1
            if row.ai_first:
                bucket["ai_first"] += 1
            if row.transferred:
                bucket["transferred"] += 1
            if row.reopen_lifetime:
                bucket["reopen"] += row.reopen_lifetime
            if row.outcome == "ai_end_to_end":
                bucket["ai_end_to_end"] += 1
            elif row.outcome == "direct_cs":
                bucket["direct_cs"] += 1

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
    populated = [row for row in by_ticket_id if not _ticket_sort_absent(row, sort_by)]
    missing = [row for row in by_ticket_id if _ticket_sort_absent(row, sort_by)]
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


def _ticket_sort_absent(ticket: TicketRow, name: str) -> bool:
    """Whether this ticket has no value to sort on for `name`.

    An empty `tool_error_codes` tuple means "no tool reported a failure",
    which is an absent value rather than a low one -- otherwise sorting the
    column descending would surface the error-free tickets first in one
    direction and bury them in the other.
    """
    value = getattr(ticket, name)
    return value is None or value == ()


def _ticket_sort_value(
    ticket: TicketRow,
    name: str,
) -> tuple[tuple[int, int | str], ...]:
    value = getattr(ticket, name)
    if isinstance(value, tuple):
        # Sort on the tokens themselves, not `str(tuple)`, so the order the
        # user sees matches the order the column renders.
        return tuple((1, token) for token in value)
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


def _matches_multi_dimension(
    ticket: TicketRow, name: str, selected: frozenset[str] | None
) -> bool:
    """True when ``ticket`` satisfies a multi-select dimension filter.

    ``selected == {_HAS_VALUE}`` (C6) means "any value other than the
    dimension's own missing sentinel" rather than one specific value.
    """
    if selected is None:
        return True
    value = _ticket_filter_value(ticket, name)
    if selected == frozenset({_HAS_VALUE}):
        return value not in (_MISSING, _NO_SKILL)
    return value in selected


def _ticket_filter_value(ticket: TicketRow, name: str) -> str:
    value = getattr(ticket, name)
    if value is not None:
        return value
    # A ticket-row skill of None means "not exactly one recorded skill" — most
    # often zero. The Explorer's skill filter options come from the segment
    # bucket labels, so this fallback must match the label those options use.
    return _NO_SKILL if name == "skill" else _MISSING


def _tool_error_code_allowlist(snapshot: DashboardSnapshot) -> frozenset[str]:
    """Every `<tool>:<code>` pair present in this snapshot.

    Unlike the scalar dimensions there is no segment bucket to union in: the
    field is not aggregated anywhere, so the tickets are the only source. A
    requested pair absent from the snapshot is rejected rather than returning
    an empty page, matching how every other dimension filter behaves.
    """
    return frozenset(
        token for ticket in snapshot.tickets for token in ticket.tool_error_codes
    )


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
    ai_review_cache: AIReviewCache | None,
    ai_tag_cache: AiTagCache | None,
    tickets: tuple[TicketRow, ...],
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
            ai_review_cache,
            tpe_status_index,
            ai_tag_cache,
            tickets,
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
            ai_review_cache,
            tpe_status_index,
            ai_tag_cache,
            tickets,
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
        "tool_error_codes": _tool_error_code_counts(result.sessions),
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
    ai_review_cache: AIReviewCache | None,
    tpe_status_index: Mapping[tuple[str, str | None], str],
    ai_tag_cache: AiTagCache | None,
    tickets: tuple[TicketRow, ...],
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
                ai_review_cache,
                tpe_status_index,
                ai_tag_cache,
                tickets,
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
        "ai_tag_coverage": _ai_tag_coverage_payload(
            weekly,
            week_definition,
            ai_tag_cache,
            tickets,
        ),
        "ai_review": _ai_review_payload(sessions, weekly, ai_review_cache),
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
    }


def _ai_tag_coverage_payload(
    weekly: tuple[WeeklySummary, ...],
    week_definition: str,
    cache: AiTagCache | None,
    tickets: tuple[TicketRow, ...],
) -> dict[str, object] | None:
    """Two-universe `#AI` coverage: Freshdesk's `#AI`-tagged tickets vs the
    Langfuse-known ticket population.

    Langfuse derives `cohort_week` from `turn0_timestamp`, Freshdesk from
    `created_at` -- the same ticket can land in different weeks on each side.
    Membership (miss / untagged) is therefore checked against the FULL,
    week-independent id set on each side, built once below; only bucket
    *assignment* uses each side's own week/day. Filtering by week before
    comparing would silently misreport a boundary ticket as missing.
    """
    if cache is None or cache.fetched_at is None:
        return None
    fetched_weeks = frozenset(cache.fetched_weeks)
    observed_weeks = {
        summary.cohort_week.isoformat()
        for summary in weekly
        if summary.cohort_week.isoformat() in fetched_weeks
    }

    def _weekday_ok(opened_at: str, label: str) -> bool:
        if week_definition == "mon_sun":
            return True
        opened = _parse_utc_iso(opened_at, label).astimezone(_VIETNAM_TIMEZONE)
        return opened.weekday() < 5

    ai_records = [
        record for record in cache.records
        if _weekday_ok(record.opened_at, "ai tag opened_at")
    ]
    langfuse_rows = [
        row for row in tickets if _weekday_ok(row.opened_at, "ticket opened_at")
    ]
    ai_tagged_ids = {record.ticket_id for record in ai_records}
    langfuse_ids = {row.ticket_id for row in langfuse_rows}

    week_ai: dict[str, list[AiTagRecord]] = {week: [] for week in observed_weeks}
    week_langfuse: dict[str, list[TicketRow]] = {week: [] for week in observed_weeks}
    week_unfetched_ids: dict[str, set[str]] = {week: set() for week in observed_weeks}
    day_ai: dict[str, list[AiTagRecord]] = {}
    day_langfuse: dict[str, list[TicketRow]] = {}
    day_unfetched_ids: dict[str, set[str]] = {}
    for record in ai_records:
        if record.cohort_week not in observed_weeks:
            continue
        week_ai[record.cohort_week].append(record)
        opened = _parse_utc_iso(record.opened_at, "ai tag opened_at").astimezone(_VIETNAM_TIMEZONE)
        day_ai.setdefault(opened.date().isoformat(), []).append(record)
    for row in langfuse_rows:
        if row.cohort_week not in observed_weeks:
            continue
        opened = _parse_utc_iso(row.opened_at, "ticket opened_at")
        fetched_at = _parse_utc_iso(cache.fetched_weeks[row.cohort_week], "fetched timestamp")
        day_key = opened.astimezone(_VIETNAM_TIMEZONE).date().isoformat()
        week_langfuse[row.cohort_week].append(row)
        day_langfuse.setdefault(day_key, []).append(row)
        if opened >= fetched_at:
            # This ticket's own week was fetched before the ticket even opened,
            # so Freshdesk was never actually checked for its #AI tag yet.
            # Default it to "has tag" rather than reporting fetch lag as a miss.
            week_unfetched_ids[row.cohort_week].add(row.ticket_id)
            day_unfetched_ids.setdefault(day_key, set()).add(row.ticket_id)

    day_keys = sorted(set(day_ai) | set(day_langfuse))
    return {
        "source": "freshdesk",
        "source_start_week": ENTRY_COVERAGE_START_WEEK,
        "fetched_at": cache.fetched_at,
        "by_week": {
            key: _ai_tag_coverage_bucket(
                week_ai[key],
                week_langfuse[key],
                ai_tagged_ids,
                langfuse_ids,
                week_unfetched_ids[key],
            )
            for key in sorted(week_ai)
        },
        "by_day": {
            key: _ai_tag_coverage_bucket(
                day_ai.get(key, ()),
                day_langfuse.get(key, ()),
                ai_tagged_ids,
                langfuse_ids,
                day_unfetched_ids.get(key, frozenset()),
            )
            for key in day_keys
        },
    }


def _ai_tag_coverage_bucket(
    ai_records: Sequence[AiTagRecord],
    langfuse_rows: Sequence[TicketRow],
    ai_tagged_ids: AbstractSet[str],
    langfuse_ids: AbstractSet[str],
    unfetched_ids: AbstractSet[str],
) -> dict[str, object]:
    """Aggregate one bucket. Grain-agnostic, like `_entry_coverage_bucket()`.

    The ids sort as strings, not `key=int`: `_validate_ai_tag_coverage_bucket`
    checks `ids == sorted(ids)` on the stored list, which is a string compare.
    Langfuse ticket ids are not all the same width (a handful of 4-, 5-, 8- and
    10-digit ones exist alongside the 7-digit Freshdesk ones), so a numeric sort
    disagrees with that check and fails the whole snapshot.

    `ai_tagged_count` stays a Freshdesk-side count (`len(ai_records)`,
    including `missed_ids`) and `langfuse_count` a Langfuse-side count --
    the two are independent populations that can bucket the same ticket into
    different weeks/days (see `_ai_tag_coverage_payload`'s docstring).
    `union_count` used to be `ai_tagged_count + untagged_count`, which adds a
    Freshdesk-side total to a Langfuse-side total and can fall below
    `langfuse_count` whenever a tagged ticket's Freshdesk bucket differs from
    its Langfuse bucket. It is a true union instead: every Langfuse ticket in
    this bucket, plus every Freshdesk `#AI` ticket in this bucket that never
    reached Langfuse at all (`missed_ids`) -- always >= `langfuse_count`.
    """
    missed_ids = sorted(
        record.ticket_id for record in ai_records if record.ticket_id not in langfuse_ids
    )
    untagged_ids = sorted(
        row.ticket_id
        for row in langfuse_rows
        if row.ticket_id not in ai_tagged_ids and row.ticket_id not in unfetched_ids
    )
    ai_tagged_count = len(ai_records)
    untagged_count = len(untagged_ids)
    return {
        "ai_tagged_count": ai_tagged_count,
        "langfuse_count": len(langfuse_rows),
        "union_count": len(langfuse_rows) + len(missed_ids),
        "missed_count": len(missed_ids),
        "untagged_count": untagged_count,
        "missed_ticket_ids": missed_ids,
        "untagged_ticket_ids": untagged_ids,
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
        "app": {},
    }
    response_dimension_counts: dict[str, dict[str, dict[str, int]]] = {
        "skill": {},
        "issue_category": {},
        "app": {},
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
            "app": _safe_dimension(session.dimensions.app),
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
            "app": _safe_dimension(session.dimensions.app),
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
                    "app": _safe_dimension(session.dimensions.app),
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


def _ai_review_payload(
    sessions: tuple[SessionMetrics, ...],
    weekly: tuple[WeeklySummary, ...],
    cache: "AIReviewCache | None",
) -> dict[str, object] | None:
    """Bucket Freshdesk AI post-review (hậu kiểm) at both week and day grain.

    Mirrors `_csat_payload`'s shape and, like it, keys `by_day` on the
    session's own Langfuse turn0 timestamp rather than
    `AIReviewRecord.opened_at`. The two can fall in different calendar weeks
    for the same ticket (opened long before its AI activity), and week
    membership here is already decided by `session.cohort_week` -- keying the
    day off a different clock let a day slip outside the week that scoped it
    in, tripping `view.ai_review contains a day outside this view`.
    """
    if cache is None or cache.fetched_at is None:
        return None
    fetched_weeks = frozenset(cache.fetched_weeks)
    observed_weeks = {
        summary.cohort_week
        for summary in weekly
        if summary.cohort_week.isoformat() in fetched_weeks
    }
    records_by_ticket = {record.ticket_id: record for record in cache.records}
    scoped = tuple(
        session
        for session in sessions
        if _is_safe_ticket_id(session.session_id)
        and session.cohort_week in observed_weeks
        and session.session_id in records_by_ticket
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
            key: _ai_review_bucket(members, records_by_ticket)
            for key, members in sorted(week_members.items())
        },
        "by_day": {
            key: _ai_review_bucket(members, records_by_ticket)
            for key, members in sorted(day_members.items())
        },
    }


def _ai_review_bucket(
    sessions: Sequence[SessionMetrics],
    records_by_ticket: Mapping[str, "AIReviewRecord"],
) -> dict[str, object]:
    """Aggregate one bucket of tickets, whatever key selected them.

    Grain-agnostic on purpose: a day bucket and a week bucket are the same
    computation over a different member list, so the two can never drift.

    Two denominators, never the total ticket count: `reviewed_ticket_count`
    (a SUM, not a ticket count -- `cf_s_ln_hu_kim_ai` summed over every rated
    ticket, since `cf_s_ln_hu_kim_ai` only exists from 2026-08-21 onward so a
    `None`/`0` on an older *rated* ticket is a field-availability gap, not
    proof of zero reviews, and defaults to 1; an unrated ticket contributes
    nothing to this sum regardless of its review count) and `rated_ticket_count`
    (a rating label present).

    `evaluated_ticket_count` and `unrated_reviewed_ticket_count` are ticket
    counts, not sums, and cover the tickets `reviewed_ticket_count` leaves
    out: a rated ticket is "evaluated" (same population as
    `rated_ticket_count`); an unrated ticket with `cf_s_ln_hu_kim_ai >= 1` was
    reviewed but never re-rated ("Chưa đánh giá lại"), and counts as
    evaluated too. The two are disjoint by construction, so
    `evaluated_ticket_count == rated_ticket_count + unrated_reviewed_ticket_count`.
    """
    outcome_counts = {outcome: _empty_ai_review_counts() for outcome in _OUTCOMES}
    dimension_counts: dict[str, dict[str, dict[str, int]]] = {
        "skill": {},
        "issue_category": {},
        "app": {},
    }
    review_count_counts: dict[str, dict[str, int]] = {}
    totals = _empty_ai_review_counts()
    for session in sessions:
        record = records_by_ticket[session.session_id]
        outcome = _outcome(session.outcome)
        _increment_ai_review_counts(totals, record)
        _increment_ai_review_counts(outcome_counts[outcome], record)
        dimension_values = {
            "skill": _skill_bucket(session),
            "issue_category": _safe_dimension(session.dimensions.issue_category),
            "app": _safe_dimension(session.dimensions.app),
        }
        for dimension, value in dimension_values.items():
            counts = dimension_counts[dimension].setdefault(
                value, _empty_ai_review_counts()
            )
            _increment_ai_review_counts(counts, record)
        if record.rating is not None or (
            record.review_count is not None and record.review_count >= 1
        ):
            review_count_key = (
                str(record.review_count) if record.review_count is not None else "0"
            )
            counts = review_count_counts.setdefault(
                review_count_key, _empty_ai_review_counts()
            )
            _increment_ai_review_counts(counts, record)
    return {
        **totals,
        "by_outcome": outcome_counts,
        "by_dimension": {
            dimension: [
                {"value": value, **counts}
                for value, counts in sorted(
                    values.items(),
                    key=lambda item: (
                        -item[1]["reviewed_ticket_count"],
                        _natural_string_sort_key(item[0]),
                    ),
                )
            ]
            for dimension, values in dimension_counts.items()
        },
        "by_review_count": [
            {"value": value, **counts}
            for value, counts in sorted(review_count_counts.items(), key=lambda item: int(item[0]))
        ],
    }


def _empty_ai_review_counts() -> dict[str, int]:
    return {key: 0 for key in _AI_REVIEW_COUNT_KEYS}


def _increment_ai_review_counts(
    counts: dict[str, int],
    record: "AIReviewRecord",
) -> None:
    reviewed = record.review_count is not None and record.review_count >= 1
    if record.rating is not None:
        counts["rated_ticket_count"] += 1
        counts[f"{record.rating}_count"] += 1
        counts["evaluated_ticket_count"] += 1
        counts["reviewed_ticket_count"] += record.review_count if reviewed else 1
    elif reviewed:
        counts["unrated_reviewed_ticket_count"] += 1
        counts["evaluated_ticket_count"] += 1


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


def _segments(
    sessions: tuple[SessionMetrics, ...],
    safe_intents: Mapping[str, str | None],
) -> dict[str, dict[str, dict[str, int]]]:
    result: dict[str, dict[str, dict[str, int]]] = {}
    for dimension in _SEGMENTS:
        buckets: dict[str, dict[str, int]] = {}
        for session in sessions:
            value = _segment_value(session, dimension, safe_intents)
            bucket = buckets.setdefault(
                value,
                {
                    "total": 0,
                    "ai_first": 0,
                    "transferred": 0,
                    "reopen": 0,
                    "ai_end_to_end": 0,
                    "direct_cs": 0,
                },
            )
            bucket["total"] += 1
            bucket["ai_first"] += int(session.ai_first)
            bucket["transferred"] += int(session.transferred)
            bucket["reopen"] += session.reopen_lifetime or 0
            if session.outcome == "ai_end_to_end":
                bucket["ai_end_to_end"] += 1
            elif session.outcome == "direct_cs":
                bucket["direct_cs"] += 1
        # The missing bucket is always present, making the consumer's closure
        # logic deterministic even when this run happens to have no missing
        # data. `skill` uses its own always-present "chưa ghi nhận" bucket
        # instead, since _MISSING would sit alongside it meaning nothing.
        missing_label = _NO_SKILL if dimension == "skill" else _MISSING
        buckets.setdefault(
            missing_label,
            {
                "total": 0,
                "ai_first": 0,
                "transferred": 0,
                "reopen": 0,
                "ai_end_to_end": 0,
                "direct_cs": 0,
            },
        )
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


def _tool_error_code_counts(
    sessions: tuple[SessionMetrics, ...],
) -> list[dict[str, object]]:
    """Ticket counts per `<tool>:<code>` pair, most frequent first.

    Top level rather than a `views[*].segments` entry on purpose: a segment
    must partition the sessions exactly once (`_validate_view` reconciles each
    dimension's `transferred` total against the transfer denominator) and this
    dimension cannot -- a ticket carrying two pairs would be counted twice.
    Same shape of exception as `unmapped_tpe_codes`.

    A ticket is counted once per distinct pair it carries, so the totals sum
    above the number of tickets with an error. That is the intended reading:
    the question is "how many tickets did this tool fail on", per tool.
    """
    counts: Counter[str] = Counter()
    for session in sessions:
        counts.update(set(session.dimensions.tool_error_codes))
    return [
        {"code": code, "total": total}
        for code, total in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]


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
    ai_review_rating_by_ticket: Mapping[str, str | None],
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
        tool_error_codes=tuple(dims.tool_error_codes),
        ai_review_rating=ai_review_rating_by_ticket.get(session.session_id),
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






def _parse_multi_ticket_filter(
    value: str | None,
    allowed: frozenset[str],
    name: str,
) -> frozenset[str] | None:
    """Comma-separated multi-select value, same convention as ``cohort_weeks``.

    A bare single value (no comma) parses identically to the old exact-match
    filter, so this is a superset of the previous single-select behaviour.

    ``_HAS_VALUE`` (C6, "Chỉ ticket có ...") is a reserved sentinel meaning
    "any real value" rather than one specific value from ``allowed`` -- it is
    recognised here, before the allowlist check, and never combined with a
    real value in the same request.
    """
    if value is None:
        return None
    if value == _HAS_VALUE:
        return frozenset({_HAS_VALUE})
    pieces = value.split(",")
    if not pieces or len(set(pieces)) != len(pieces):
        raise ValueError(f"{name} is invalid")
    if any(piece not in allowed for piece in pieces):
        raise ValueError(f"{name} is invalid")
    return frozenset(pieces)




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
    tool_error_codes = fields.get("tool_error_codes")
    if isinstance(tool_error_codes, list):
        fields["tool_error_codes"] = tuple(tool_error_codes)
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


def _ai_tag_record_dict(record: AiTagRecord) -> dict[str, object]:
    if not isinstance(record, AiTagRecord):
        raise ValueError("ai tag tickets are invalid")
    return {
        "ticket_id": record.ticket_id,
        "opened_at": record.opened_at,
        "cohort_week": record.cohort_week,
    }


def _ai_tag_record_from_storage(value: object) -> AiTagRecord:
    mapping = _require_mapping(value, "ai tag ticket")
    _require_exact_keys(
        mapping,
        {"ticket_id", "opened_at", "cohort_week"},
        "ai tag ticket",
    )
    try:
        return AiTagRecord(**dict(mapping))
    except (TypeError, AiTagCacheError) as error:
        raise ValueError("stored ai tag ticket is invalid") from error


def _safe_dimension(value: str) -> str:
    try:
        return _safe_string(value, "dimension")
    except ValueError:
        return _MISSING




def _safe_optional(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return _safe_string(value, "dimension")
    except ValueError:
        return None










def _outcome(value: str | None) -> str:
    return value if value in _OUTCOMES else "unclassified"


def _quality_label(value: object) -> str:
    return value if value in _QUALITY_LABELS else "unknown_quality_issue"
