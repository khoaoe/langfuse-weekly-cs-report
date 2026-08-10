from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta, timezone
from types import MappingProxyType
from typing import Mapping, Sequence

from .categories import Taxonomy, extract_dimensions
from .classification import classify_session, normalize_trace
from .cohort import VIETNAM_TIMEZONE, is_week_fully_mature
from .enrichment import (
    TraceEnrichment,
    apply_trace_enrichment,
    transfer_trigger_for_trace,
)
from .models import (
    AnalysisResult,
    CandidateSelection,
    CategoryResult,
    CohortWindow,
    GateStatus,
    InvariantError,
    QualityIssue,
    SessionMetrics,
    TraceRecord,
    TransferCategories,
    WeeklySummary,
)

_LEGACY_TPE_CATEGORIES = frozenset(
    {
        "1", "2", "6", "7", "8", "9", "10", "11", "12", "13", "14",
        "15", "16", "17", "18", "19", "20", "21", "22", "23", "24",
        "25", "26", "27", "28", "29", "30",
    }
)


@dataclass(frozen=True)
class SamePeriodBaseline:
    weeks_used: int
    ai_first_rate: float
    reopen_lifetime_rate: float | None


@dataclass(frozen=True)
class SamePeriodComparison:
    cutoff_date: date
    cutoff_weekday: int
    current: WeeklySummary
    baseline: SamePeriodBaseline
    by_week: Mapping[date, WeeklySummary]


def normalize_raw_traces(
    raw_traces: Sequence[Mapping[str, object]],
) -> tuple[tuple[TraceRecord, ...], tuple[QualityIssue, ...], int]:
    """Normalize one deterministic copy of each trace ID.

    Langfuse pages should not overlap, but a repeated boundary item must not
    manufacture a duplicate turn and quarantine an otherwise valid ticket.
    Items without a usable ID cannot be deduplicated and remain visible as
    normalization issues.
    """
    seen_trace_ids: set[str] = set()
    deduplicated: list[Mapping[str, object]] = []
    for raw in raw_traces:
        trace_id = raw.get("id")
        if isinstance(trace_id, str) and trace_id:
            if trace_id in seen_trace_ids:
                continue
            seen_trace_ids.add(trace_id)
        deduplicated.append(raw)

    records: list[TraceRecord] = []
    issues: list[QualityIssue] = []
    for raw in deduplicated:
        normalized = normalize_trace(dict(raw))
        if isinstance(normalized, TraceRecord):
            records.append(normalized)
        else:
            issues.append(normalized)
    return tuple(records), tuple(issues), len(deduplicated)


def _in_window(turn0: TraceRecord, window: CohortWindow) -> bool:
    timestamp = turn0.timestamp.astimezone(VIETNAM_TIMEZONE)
    if window.complete_start_local <= timestamp < window.complete_end_exclusive_local:
        return True
    return (
        window.wtd_start_local is not None
        and window.wtd_start_local <= timestamp <= window.as_of.astimezone(VIETNAM_TIMEZONE)
    )


def _deduplicate_keyed_issues(
    issues: Sequence[QualityIssue],
) -> tuple[QualityIssue, ...]:
    by_session: dict[str, QualityIssue] = {}
    ordered = sorted(
        (issue for issue in issues if issue.session_id),
        key=lambda issue: (
            issue.session_id or "",
            issue.reason,
            issue.trace_id or "",
            (
                issue.timestamp.astimezone(timezone.utc).isoformat()
                if issue.timestamp is not None
                else ""
            ),
        ),
    )
    for issue in ordered:
        if issue.session_id and issue.session_id not in by_session:
            by_session[issue.session_id] = issue
    return tuple(by_session.values())


def select_candidate_sessions(
    records: Sequence[TraceRecord],
    issues: Sequence[QualityIssue],
    window: CohortWindow,
) -> CandidateSelection:
    unkeyed = tuple(issue for issue in issues if not issue.session_id)
    keyed = list(_deduplicate_keyed_issues(issues))
    invalid_session_ids = {
        issue.session_id for issue in keyed if issue.session_id is not None
    }

    grouped: dict[str, list[TraceRecord]] = defaultdict(list)
    for record in records:
        grouped[record.session_id].append(record)

    eligible: dict[str, tuple[TraceRecord, ...]] = {}
    left_censored: list[str] = []
    pre_window_start: list[str] = []
    for session_id in sorted(grouped):
        if session_id in invalid_session_ids:
            continue
        ordered = tuple(
            sorted(grouped[session_id], key=lambda item: (item.turn, item.timestamp, item.id))
        )
        first = ordered[0]
        first_local = first.timestamp.astimezone(VIETNAM_TIMEZONE)
        if first_local < window.complete_start_local:
            # The 14-day lookback exists solely to find canonical first traces.
            # A continuation must never be assigned to a later cohort week.
            if any(_in_window(item, window) for item in ordered[1:]):
                pre_window_start.append(session_id)
            continue
        if not _in_window(first, window):
            continue
        eligible[session_id] = ordered

    return CandidateSelection(
        eligible=eligible,
        weekend_start=(),
        left_censored=tuple(left_censored),
        invalid_keyed=_deduplicate_keyed_issues(keyed),
        unkeyed=unkeyed,
        window=window,
        pre_window_start=tuple(pre_window_start),
    )


def nearest_rank(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _cohort_weeks(window: CohortWindow) -> tuple[tuple[date, str], ...]:
    weeks: list[tuple[date, str]] = []
    current = window.complete_start_local.date()
    complete_end = window.complete_end_exclusive_local.date()
    while current < complete_end:
        weeks.append((current, "complete"))
        current += timedelta(weeks=1)
    if window.wtd_start_local is not None:
        weeks.append((window.wtd_start_local.date(), "wtd"))
    return tuple(weeks)


def _summarize_sessions(
    sessions: Sequence[SessionMetrics],
    window: CohortWindow,
    week_definition: str = "mon_sun",
) -> tuple[WeeklySummary, ...]:
    if week_definition not in {"mon_sun", "mon_fri"}:
        raise ValueError("week_definition must be mon_sun or mon_fri")
    by_week: dict[date, list[SessionMetrics]] = defaultdict(list)
    for session in sessions:
        if week_definition == "mon_sun" or not session.is_weekend_start:
            by_week[session.cohort_week].append(session)

    summaries: list[WeeklySummary] = []
    for cohort_week, cohort_status in _cohort_weeks(window):
        effective_status = cohort_status
        if cohort_status == "wtd":
            reporting_last_day = cohort_week + timedelta(
                days=4 if week_definition == "mon_fri" else 6
            )
            if window.as_of.astimezone(VIETNAM_TIMEZONE).date() > reporting_last_day:
                effective_status = "complete"
        weekly_sessions = by_week.get(cohort_week, [])
        total = len(weekly_sessions)
        ai_first = [session for session in weekly_sessions if session.ai_first]
        ai_end_to_end_count = sum(
            session.outcome == "ai_end_to_end" for session in weekly_sessions
        )
        ai_then_cs_count = sum(
            session.outcome == "ai_then_cs" for session in weekly_sessions
        )
        direct_cs_count = sum(
            session.outcome == "direct_cs" for session in weekly_sessions
        )
        unclassified_count = sum(
            session.outcome == "unclassified" for session in weekly_sessions
        )
        if is_week_fully_mature(cohort_week, window.as_of, week_definition):
            reopen_7d_values = [
                session.reopen_within_7d
                for session in ai_first
                if session.reopen_within_7d is not None
            ]
            reopen_7d_denominator: int | None = len(reopen_7d_values)
            reopen_7d_rate = (
                sum(reopen_7d_values) / reopen_7d_denominator
                if reopen_7d_denominator
                else None
            )
        else:
            reopen_7d_denominator = None
            reopen_7d_rate = None
        reopen_lifetime_values = [
            session.reopen_lifetime
            for session in ai_first
            if session.reopen_lifetime is not None
        ]
        reopen_lifetime_numerator = sum(reopen_lifetime_values)
        reopen_lifetime_denominator = len(reopen_lifetime_values)
        reopen_lifetime_rate = (
            reopen_lifetime_numerator / reopen_lifetime_denominator
            if reopen_lifetime_denominator
            else None
        )
        reply_counts = [session.ai_reply_count for session in weekly_sessions]
        ai_reply_counts = [session.ai_reply_count for session in ai_first]
        gt4_turn_with_cs = sum(
            session.turn_count > 3 and session.transferred for session in weekly_sessions
        )
        gt4_turn_without_cs = sum(
            session.turn_count > 3 and not session.transferred for session in weekly_sessions
        )
        max_replies_rule_fired = sum(
            "max_replies_exceeded" in session.guardrail_rules
            for session in weekly_sessions
        )
        summaries.append(
            WeeklySummary(
                cohort_week=cohort_week,
                cohort_status=effective_status,
                total_tickets=total,
                ai_first_count=len(ai_first),
                ai_first_rate=len(ai_first) / total if total else 0.0,
                ai_end_to_end_count=ai_end_to_end_count,
                ai_then_cs_count=ai_then_cs_count,
                direct_cs_count=direct_cs_count,
                unclassified_count=unclassified_count,
                reopen_7d_rate=reopen_7d_rate,
                reopen_7d_denominator=reopen_7d_denominator,
                reopen_lifetime_rate=reopen_lifetime_rate,
                ai_reply_p50=nearest_rank(reply_counts, 0.5),
                ai_reply_p90=nearest_rank(reply_counts, 0.9),
                ai_reply_max=max(reply_counts) if reply_counts else None,
                as_of=window.as_of,
                week_definition=week_definition,
                has_data=bool(weekly_sessions),
                reopen_lifetime_numerator=reopen_lifetime_numerator,
                reopen_lifetime_denominator=reopen_lifetime_denominator,
                ai_reply_mean_ai_first=(
                    sum(ai_reply_counts) / len(ai_reply_counts)
                    if ai_reply_counts
                    else None
                ),
                gt4_turn_with_cs=gt4_turn_with_cs,
                gt4_turn_without_cs=gt4_turn_without_cs,
                max_replies_rule_fired=max_replies_rule_fired,
            )
        )
    return tuple(summaries)


def _evaluate_gate_inputs(
    sessions: Sequence[SessionMetrics],
    transfers: dict[str, TransferCategories],
    selection: CandidateSelection,
) -> GateStatus:
    invalid_session_ids = {
        issue.session_id for issue in selection.invalid_keyed if issue.session_id
    }
    structural_denominator = len(sessions) + len(invalid_session_ids)
    structural_rate = (
        len(invalid_session_ids) / structural_denominator
        if structural_denominator
        else 0.0
    )
    structural_blocked = structural_rate > 0.05
    reasons: list[str] = []
    if structural_blocked:
        reasons.append("structural_invalid_rate_gt_5pct")
    return GateStatus(
        core_allowed=not structural_blocked,
        business_allowed=not structural_blocked,
        tpe_allowed=not structural_blocked,
        guardrail_allowed=not structural_blocked,
        reasons=tuple(reasons),
        structural_invalid_rate=structural_rate,
    )


def _v2_transfer_categories(metrics: SessionMetrics) -> TransferCategories:
    """Compatibility-only categories for frozen scoring/debug callers.

    Dashboard dimensions remain on ``metrics.dimensions``. This frozen legacy
    shape deliberately uses only existing browser allowlist values, avoiding
    both the obsolete observation path and fabricated keyword fallbacks.
    """
    dimensions = metrics.dimensions
    legacy_tpe_case = (
        str(dimensions.tpe_case)
        if dimensions.tpe_case is not None
        and str(dimensions.tpe_case) in _LEGACY_TPE_CATEGORIES
        else "not_applicable"
    )
    return TransferCategories(
        business=CategoryResult("not_applicable"),
        tpe=CategoryResult(legacy_tpe_case),
        guardrail_rule=CategoryResult("not_applicable"),
    )


def analyze_sessions(
    selection: CandidateSelection,
    taxonomy: Taxonomy,
    trace_enrichment: Mapping[str, TraceEnrichment] | None = None,
) -> AnalysisResult:
    sessions: list[SessionMetrics] = []
    transfers: dict[str, TransferCategories] = {}
    invalid_keyed = list(selection.invalid_keyed)
    analyzed_eligible: dict[str, tuple[TraceRecord, ...]] = {}

    for session_id in sorted(selection.eligible):
        traces = selection.eligible[session_id]
        classified = classify_session(traces, selection.window, taxonomy.transfer_texts)
        if isinstance(classified, QualityIssue):
            invalid_keyed.append(classified)
            continue
        dimensions = (
            extract_dimensions(traces[0], taxonomy)
            if taxonomy.version == "v2"
            else classified.dimensions
        )
        if taxonomy.version == "v2" and trace_enrichment is not None:
            dimensions, guardrail_rules = apply_trace_enrichment(
                dimensions, traces, trace_enrichment
            )
            transfer_trigger = transfer_trigger_for_trace(
                classified.first_transfer_trace_id,
                trace_enrichment,
            )
        else:
            guardrail_rules = ()
            transfer_trigger = None
        classified = replace(
            classified,
            as_of=selection.window.as_of,
            dimensions=dimensions,
            guardrail_rules=guardrail_rules,
            transfer_trigger=transfer_trigger,
        )
        sessions.append(classified)
        analyzed_eligible[session_id] = traces
        if classified.first_transfer_trace_id is not None:
            transfers[session_id] = _v2_transfer_categories(classified)

    sessions_tuple = tuple(sorted(sessions, key=lambda item: item.session_id))
    analyzed_selection = replace(
        selection,
        eligible=analyzed_eligible,
        invalid_keyed=_deduplicate_keyed_issues(invalid_keyed),
    )
    weekly_mon_sun = _summarize_sessions(
        sessions_tuple, selection.window, "mon_sun"
    )
    weekly_mon_fri = _summarize_sessions(
        sessions_tuple, selection.window, "mon_fri"
    )
    gate_status = _evaluate_gate_inputs(sessions_tuple, transfers, analyzed_selection)
    result = AnalysisResult(
        sessions=sessions_tuple,
        transfers=transfers,
        selection=analyzed_selection,
        weekly=weekly_mon_sun,
        gate_status=gate_status,
        weekly_mon_sun=weekly_mon_sun,
        weekly_mon_fri=weekly_mon_fri,
    )
    validate_invariants(result)
    return result


def summarize_weeks(
    result: AnalysisResult,
    window: CohortWindow,
    week_definition: str = "mon_sun",
) -> tuple[WeeklySummary, ...]:
    if window != result.selection.window:
        raise InvariantError("summary window must match the analysis window")
    return _summarize_sessions(result.sessions, window, week_definition)


def summarize_same_period(
    result: AnalysisResult,
    week_definition: str = "mon_sun",
) -> SamePeriodComparison | None:
    if week_definition not in {"mon_sun", "mon_fri"}:
        raise ValueError("week_definition must be mon_sun or mon_fri")
    window = result.selection.window
    if window.wtd_start_local is None:
        return None

    current_week = window.wtd_start_local.date()
    cutoff_date = window.as_of.astimezone(VIETNAM_TIMEZONE).date() - timedelta(days=1)
    if cutoff_date < current_week:
        return None
    current_week_last_day = current_week + timedelta(
        days=4 if week_definition == "mon_fri" else 6
    )
    if cutoff_date >= current_week_last_day:
        return None
    cutoff_weekday = cutoff_date.isoweekday()

    filtered = tuple(
        session
        for session in result.sessions
        if _is_in_same_period_slice(session, cutoff_weekday)
    )
    summaries = _summarize_sessions(filtered, window, week_definition)
    current = next(
        summary
        for summary in summaries
        if summary.cohort_status == "wtd"
    )
    baseline = tuple(
        summary
        for summary in sorted(
            (
                item
                for item in summaries
                if item.cohort_status == "complete" and item.total_tickets > 0
            ),
            key=lambda item: item.cohort_week,
            reverse=True,
        )[:4]
    )
    if len(baseline) < 2:
        return None
    by_week = MappingProxyType({
        summary.cohort_week: summary
        for summary in summaries
    })

    reopen_rates = [
        summary.reopen_lifetime_rate
        for summary in baseline
        if summary.reopen_lifetime_rate is not None
    ]
    return SamePeriodComparison(
        cutoff_date=cutoff_date,
        cutoff_weekday=cutoff_weekday,
        current=current,
        baseline=SamePeriodBaseline(
            weeks_used=len(baseline),
            ai_first_rate=sum(summary.ai_first_rate for summary in baseline) / len(baseline),
            reopen_lifetime_rate=(
                sum(reopen_rates) / len(reopen_rates) if reopen_rates else None
            ),
        ),
        by_week=by_week,
    )


def _is_in_same_period_slice(
    session: SessionMetrics,
    cutoff_weekday: int,
) -> bool:
    local_date = session.turn0_timestamp.astimezone(VIETNAM_TIMEZONE).date()
    start = session.cohort_week
    end = start + timedelta(days=cutoff_weekday)
    return start <= local_date < end


def evaluate_gates(result: AnalysisResult) -> GateStatus:
    return _evaluate_gate_inputs(result.sessions, result.transfers, result.selection)


def validate_invariants(result: AnalysisResult) -> None:
    session_ids = [session.session_id for session in result.sessions]
    if len(session_ids) != len(set(session_ids)):
        raise InvariantError("sessions must be unique at ticket grain")

    selection = result.selection
    eligible_ids = set(selection.eligible)
    if set(session_ids) != eligible_ids:
        raise InvariantError("analyzed sessions must exactly match eligible sessions")

    weekend_ids = selection.weekend_start
    left_censored_ids = selection.left_censored
    pre_window_start_ids = selection.pre_window_start
    invalid_ids = tuple(
        issue.session_id for issue in selection.invalid_keyed if issue.session_id
    )
    if (
        len(weekend_ids) != len(set(weekend_ids))
        or len(left_censored_ids) != len(set(left_censored_ids))
        or len(pre_window_start_ids) != len(set(pre_window_start_ids))
        or len(invalid_ids) != len(set(invalid_ids))
    ):
        raise InvariantError("candidate group IDs must be unique")
    if any(
        not session_id
        for session_id in (*weekend_ids, *left_censored_ids, *pre_window_start_ids)
    ):
        raise InvariantError("candidate group IDs must be non-empty")
    if len(invalid_ids) != len(selection.invalid_keyed):
        raise InvariantError("invalid keyed issues must have session IDs")
    if any(issue.session_id is not None for issue in selection.unkeyed):
        raise InvariantError("unkeyed issues must not have session IDs")
    unkeyed_trace_ids = [
        issue.trace_id for issue in selection.unkeyed if issue.trace_id is not None
    ]
    if len(unkeyed_trace_ids) != len(set(unkeyed_trace_ids)):
        raise InvariantError("unkeyed trace IDs must be unique")

    candidate_id_groups = (
        eligible_ids,
        set(weekend_ids),
        set(left_censored_ids),
        set(pre_window_start_ids),
        set(invalid_ids),
    )
    for index, group in enumerate(candidate_id_groups):
        if any(group & other for other in candidate_id_groups[index + 1 :]):
            raise InvariantError("candidate session groups must be pairwise disjoint")

    for session in result.sessions:
        if session.cohort_status not in {"complete", "wtd"}:
            raise InvariantError("analyzed sessions must be in a reporting cohort")
        if session.is_weekend_start != (
            session.turn0_timestamp.astimezone(VIETNAM_TIMEZONE).weekday() >= 5
        ):
            raise InvariantError("weekend-start flag must match canonical first trace")
        if session.dimensions.guardrail_rule is not None:
            if session.guardrail_rules != (session.dimensions.guardrail_rule,):
                raise InvariantError("scalar guardrail rule must be an unambiguous internal rule")
        elif len(session.guardrail_rules) == 1:
            raise InvariantError("unambiguous internal guardrail rule must be projected")

    transferred_session_ids = {
        session.session_id
        for session in result.sessions
        if session.first_transfer_trace_id is not None
    }
    if set(result.transfers) != transferred_session_ids:
        raise InvariantError("categories must exist exactly once for transferred sessions")

    compatibility_override = result.weekly_mon_sun and result.weekly != result.weekly_mon_sun
    weekly_views = {
        "mon_sun": result.weekly if compatibility_override else (result.weekly_mon_sun or result.weekly),
        "mon_fri": () if compatibility_override else result.weekly_mon_fri,
    }
    for week_definition, summaries in weekly_views.items():
        if not summaries:
            continue
        if any(summary.week_definition != week_definition for summary in summaries):
            raise InvariantError("weekly summary has wrong week definition")
        for summary in summaries:
            if summary.ai_first_count != (
                summary.ai_end_to_end_count + summary.ai_then_cs_count
            ):
                raise InvariantError("AI-first weekly reconciliation failed")
            if summary.total_tickets != (
                summary.ai_end_to_end_count
                + summary.ai_then_cs_count
                + summary.direct_cs_count
                + summary.unclassified_count
            ):
                raise InvariantError("ticket weekly reconciliation failed")
            if (summary.gt4_turn_with_cs + summary.gt4_turn_without_cs) > summary.total_tickets:
                raise InvariantError("gt4 weekly reconciliation failed")
            if summary.has_data != bool(summary.total_tickets):
                raise InvariantError("weekly has_data must match ticket total")
        expected = _summarize_sessions(
            result.sessions, result.selection.window, week_definition
        )
        if tuple(summaries) != expected:
            raise InvariantError("weekly summaries do not match session metrics")

    # ``weekly`` is a deprecated compatibility alias and always exposes the
    # T2–CN view.  Retaining it prevents the frozen score/artifact path from
    # silently changing the business cohort.
    if not compatibility_override and result.weekly != (result.weekly_mon_sun or result.weekly):
        raise InvariantError("weekly compatibility alias must be mon_sun")
    if result.gate_status != _evaluate_gate_inputs(
        result.sessions, result.transfers, result.selection
    ):
        raise InvariantError("gate status does not match analysis quality")
