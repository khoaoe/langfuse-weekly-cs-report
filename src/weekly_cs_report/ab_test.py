"""A/B comparison of the two model arms carried in ``input.model_info``.

This layer is deliberately independent of the weekly snapshot pipeline: it
answers "which model is winning, right now, over a window the reader chose",
which is a different question from the governed weekly report and must not
wait on (or be blocked by) that pipeline's enrichment.

Outcome definitions are NOT redefined here. ``classify_session`` from
``classification`` stays the single source of truth for the four outcomes,
AI-first and reopen, so this section can never drift from the rest of the
dashboard.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from .categories import Taxonomy, extract_dimensions
from .classification import classify_session, normalize_trace
from .cohort import VIETNAM_TIMEZONE
from .enrichment import TraceEnrichment, apply_trace_enrichment, build_trace_enrichment
from .langfuse_client import LangfuseClient
from .models import CohortWindow, QualityIssue, TraceRecord

# Bulk range queries, same shape as the weekly pipeline's own enrichment step
# (`report.py`): one paginated fetch per observation name over the whole
# window, never one call per ticket.
_ENRICHMENT_OBSERVATION_NAMES = ("route", "execute")

# Mirrors `SEGMENT_DIMENSIONS` in BelowFold.tsx so "So sánh theo thuộc tính
# ticket" and this section always offer the same breakdown vocabulary.
DIMENSIONS: tuple[str, ...] = (
    "issue_category",
    "app",
    "product_code",
    "skill",
    "intent",
)

# Below this, a per-arm rate is noise: one flipped ticket moves it by whole
# points. The UI degrades to raw counts rather than asserting a rate.
_MIN_RELIABLE_SAMPLE = 30
_TOP_VALUES_PER_DIMENSION = 8
_TRACE_FIELDS = "core,io,metrics"


@dataclass(frozen=True)
class ArmMetrics:
    arm: str
    ticket_count: int
    share: float
    low_sample: bool
    ai_end_to_end: int
    ai_then_cs: int
    direct_cs: int
    unclassified: int
    ai_first_count: int
    transferred_count: int
    reopen_count: int
    reopen_denominator: int
    turn_total: int
    latency_p50: float | None
    latency_p95: float | None
    llm_call_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    llm_latency_p50: float | None
    llm_latency_p95: float | None
    csat_response_count: int
    csat_positive_count: int
    csat_negative_count: int


@dataclass(frozen=True)
class DailyArmPoint:
    date: str
    arm: str
    ticket_count: int
    ai_end_to_end: int
    ai_first_count: int
    transferred_count: int
    direct_cs: int
    reopen_count: int
    reopen_denominator: int
    turn_total: int
    latency_p50: float | None
    latency_p95: float | None
    total_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class DimensionArmCount:
    dimension: str
    value: str
    arm: str
    ticket_count: int
    ai_end_to_end: int


@dataclass(frozen=True)
class AbTestSnapshot:
    window_start: datetime
    window_end: datetime
    total_tickets: int
    unmatched_tickets: int
    arms: tuple[ArmMetrics, ...]
    daily: tuple[DailyArmPoint, ...]
    dimensions: Mapping[str, tuple[DimensionArmCount, ...]]
    csat_available: bool


@dataclass(frozen=True)
class _TicketFacts:
    ticket_id: str
    arm: str
    timestamp: datetime
    outcome: str
    ai_first: bool
    transferred: bool
    reopen_lifetime: int | None
    turn_count: int
    latency: float | None
    dimension_values: Mapping[str, str]


def _extract_arm(input_data: object) -> str | None:
    """The arm identity, read only from a real ticket trace.

    ``model_core`` and ``model_guardrail`` always agree inside one ticket, so
    ``model_core`` alone identifies the arm.
    """
    if not isinstance(input_data, Mapping):
        return None
    if input_data.get("source") != "ticket":
        return None
    model_info = input_data.get("model_info")
    if not isinstance(model_info, Mapping):
        return None
    model_core = model_info.get("model_core")
    return model_core if isinstance(model_core, str) and model_core else None


def _parse_trace_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _trace_latency(raw: Mapping[str, object]) -> float | None:
    """Trace latency in seconds, or None when Langfuse returned its sentinel.

    Langfuse answers ``-1`` when the caller did not request the ``metrics``
    field group; treating that as a real duration would silently poison every
    percentile.
    """
    value = raw.get("latency")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    """Nearest-rank percentile, matching ``pipeline.nearest_rank``."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _full_window(window_start: datetime, window_end: datetime) -> CohortWindow:
    """A cohort window spanning exactly the requested range.

    ``classify_session`` reads the window only to stamp a cohort status. A
    single complete span keeps every ticket in scope without importing the
    weekly report's Monday-boundary semantics, which do not apply to an
    operator-chosen range.
    """
    start_local = window_start.astimezone(VIETNAM_TIMEZONE)
    end_local = window_end.astimezone(VIETNAM_TIMEZONE)
    return CohortWindow(
        as_of=window_end,
        complete_start_local=start_local,
        complete_end_exclusive_local=end_local + timedelta(seconds=1),
        wtd_start_local=None,
        query_from_utc=window_start,
        query_to_utc=window_end,
    )


def _ticket_facts(
    raw_traces: Iterable[Mapping[str, object]],
    window: CohortWindow,
    taxonomy: Taxonomy,
    trace_enrichment: Mapping[str, TraceEnrichment],
) -> tuple[list[_TicketFacts], int]:
    """Group raw traces into per-ticket facts, one row per ticket."""
    by_ticket: dict[str, list[TraceRecord]] = defaultdict(list)
    arm_by_ticket: dict[str, str] = {}
    latency_by_trace: dict[str, float] = {}
    unmatched: set[str] = set()

    for raw in raw_traces:
        record = normalize_trace(dict(raw))
        if isinstance(record, QualityIssue):
            continue
        input_data = raw.get("input")
        arm = _extract_arm(input_data)
        if arm is None:
            # A real ticket trace that carries no model_info cannot be
            # attributed to an arm. Counting it keeps the reader honest about
            # how much of the population the comparison actually covers.
            if isinstance(input_data, Mapping) and input_data.get("source") == "ticket":
                unmatched.add(record.session_id)
            continue
        by_ticket[record.session_id].append(record)
        arm_by_ticket.setdefault(record.session_id, arm)
        latency = _trace_latency(raw)
        if latency is not None:
            latency_by_trace[record.id] = latency

    facts: list[_TicketFacts] = []
    for ticket_id, traces in by_ticket.items():
        classified = classify_session(traces, window, taxonomy.transfer_texts)
        if isinstance(classified, QualityIssue):
            continue
        ordered = sorted(traces, key=lambda item: (item.turn, item.timestamp, item.id))
        dimensions = extract_dimensions(ordered[0], taxonomy)
        dimensions, _guardrail_rules = apply_trace_enrichment(
            dimensions, ordered, trace_enrichment
        )
        # The ticket's latency is the sum of its turns: that is what the
        # customer waited for across the whole conversation.
        turn_latencies = [
            latency_by_trace[item.id]
            for item in ordered
            if item.id in latency_by_trace
        ]
        dimension_values = {
            "issue_category": dimensions.issue_category or "unknown",
            "app": dimensions.app or "unknown",
            "product_code": dimensions.product_code or "unknown",
            # None means either no skill ran or more than one distinct skill
            # ran in the ticket -- both collapse to "unknown" here, same
            # simplification the AB comparison already makes elsewhere.
            "skill": dimensions.skill or "unknown",
            "intent": dimensions.intent or "unknown",
        }
        facts.append(
            _TicketFacts(
                ticket_id=ticket_id,
                arm=arm_by_ticket[ticket_id],
                timestamp=classified.turn0_timestamp,
                outcome=classified.outcome,
                ai_first=classified.ai_first,
                transferred=classified.transferred,
                reopen_lifetime=classified.reopen_lifetime,
                turn_count=classified.turn_count,
                latency=sum(turn_latencies) if turn_latencies else None,
                dimension_values=dimension_values,
            )
        )
    return facts, len(unmatched - set(by_ticket))


def _llm_metrics_query(
    window_start: datetime, window_end: datetime
) -> dict:
    return {
        "view": "observations",
        "metrics": [
            {"measure": "count", "aggregation": "count"},
            {"measure": "totalTokens", "aggregation": "sum"},
            {"measure": "inputTokens", "aggregation": "sum"},
            {"measure": "outputTokens", "aggregation": "sum"},
            {"measure": "latency", "aggregation": "p50"},
            {"measure": "latency", "aggregation": "p95"},
        ],
        "dimensions": [{"field": "providedModelName"}],
        "fromTimestamp": window_start.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "toTimestamp": window_end.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def _llm_metrics_query_hourly(window_start: datetime, window_end: datetime) -> dict:
    """Same measures as `_llm_metrics_query`, bucketed by hour (in UTC --
    the metrics endpoint's only granularity option). Token/output-token sums
    aggregate correctly across hours, so `aggregate_ab_snapshot` re-buckets
    them into Asia/Ho_Chi_Minh calendar days itself for the daily chart.

    Latency deliberately is NOT requested here: a p95 does not sum or average
    across sub-buckets into a valid daily p95, and the endpoint only returns
    pre-aggregated percentiles, never raw samples -- so no daily latency
    metric is derived from this query.
    """
    return {
        "view": "observations",
        "metrics": [
            {"measure": "totalTokens", "aggregation": "sum"},
            {"measure": "outputTokens", "aggregation": "sum"},
        ],
        "dimensions": [{"field": "providedModelName"}],
        "fromTimestamp": window_start.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "toTimestamp": window_end.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "timeDimension": {"granularity": "hour"},
    }


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def _as_seconds(value: object) -> float | None:
    """The metrics endpoint reports observation latency in milliseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) / 1000.0


def aggregate_ab_snapshot(
    raw_traces: Iterable[Mapping[str, object]],
    window_start: datetime,
    window_end: datetime,
    taxonomy: Taxonomy,
    *,
    llm_rows: Sequence[Mapping[str, object]] = (),
    llm_daily_rows: Sequence[Mapping[str, object]] = (),
    csat_by_ticket: Mapping[str, str] | None = None,
    trace_enrichment: Mapping[str, TraceEnrichment] = MappingProxyType({}),
    arms: Sequence[str] | None = None,
) -> AbTestSnapshot:
    """`arms`, when given, both filters and orders the comparison.

    Every downstream figure (totals, shares, daily points, dimension
    breakdowns) is computed only over tickets in these arms, in this exact
    order -- so a caller-chosen [old, new] pair reads chronologically instead
    of the alphabetical order an unfiltered multi-arm view would fall back to.
    """
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("window bounds must be timezone-aware")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")

    window = _full_window(window_start, window_end)
    facts, unmatched = _ticket_facts(raw_traces, window, taxonomy, trace_enrichment)
    if arms is not None:
        allowed_arms = set(arms)
        facts = [fact for fact in facts if fact.arm in allowed_arms]
    total = len(facts)

    by_arm: dict[str, list[_TicketFacts]] = defaultdict(list)
    for fact in facts:
        by_arm[fact.arm].append(fact)

    llm_by_arm = {
        str(row.get("providedModelName")): row
        for row in llm_rows
        if isinstance(row.get("providedModelName"), str)
    }

    arm_order = list(arms) if arms is not None else sorted(by_arm)
    result_arms: list[ArmMetrics] = []
    for arm in arm_order:
        rows = by_arm.get(arm, [])
        latencies = [row.latency for row in rows if row.latency is not None]
        reopen_rows = [row for row in rows if row.reopen_lifetime is not None]
        llm = llm_by_arm.get(arm, {})
        csat_buckets = (
            [
                csat_by_ticket[row.ticket_id]
                for row in rows
                if row.ticket_id in csat_by_ticket
            ]
            if csat_by_ticket
            else []
        )
        result_arms.append(
            ArmMetrics(
                arm=arm,
                ticket_count=len(rows),
                share=len(rows) / total if total else 0.0,
                low_sample=len(rows) < _MIN_RELIABLE_SAMPLE,
                ai_end_to_end=sum(row.outcome == "ai_end_to_end" for row in rows),
                ai_then_cs=sum(row.outcome == "ai_then_cs" for row in rows),
                direct_cs=sum(row.outcome == "direct_cs" for row in rows),
                unclassified=sum(row.outcome == "unclassified" for row in rows),
                ai_first_count=sum(row.ai_first for row in rows),
                transferred_count=sum(row.transferred for row in rows),
                reopen_count=sum(row.reopen_lifetime or 0 for row in reopen_rows),
                reopen_denominator=len(reopen_rows),
                turn_total=sum(row.turn_count for row in rows),
                latency_p50=_percentile(latencies, 0.5),
                latency_p95=_percentile(latencies, 0.95),
                llm_call_count=_as_int(llm.get("count_count")),
                input_tokens=_as_int(llm.get("sum_inputTokens")),
                output_tokens=_as_int(llm.get("sum_outputTokens")),
                total_tokens=_as_int(llm.get("sum_totalTokens")),
                llm_latency_p50=_as_seconds(llm.get("p50_latency")),
                llm_latency_p95=_as_seconds(llm.get("p95_latency")),
                csat_response_count=len(csat_buckets),
                csat_positive_count=sum(
                    bucket == "positive" for bucket in csat_buckets
                ),
                csat_negative_count=sum(
                    bucket == "negative" for bucket in csat_buckets
                ),
            )
        )

    # Every metric here comes straight off the same per-ticket facts used for
    # the overall ArmMetrics -- reopen/latency keep their exact denominators
    # (ai_first tickets, tickets with a measured latency) so a daily point
    # means the same thing as the headline number, just narrowed to one day.
    daily_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0, 0])
    daily_latencies: dict[tuple[str, str], list[float]] = defaultdict(list)
    for fact in facts:
        key = (
            fact.timestamp.astimezone(VIETNAM_TIMEZONE).date().isoformat(),
            fact.arm,
        )
        counts = daily_counts[key]
        counts[0] += 1
        counts[1] += int(fact.outcome == "ai_end_to_end")
        counts[2] += int(fact.ai_first)
        counts[3] += int(fact.transferred)
        counts[4] += int(fact.outcome == "direct_cs")
        counts[6] += fact.turn_count
        if fact.reopen_lifetime is not None:
            counts[5] += fact.reopen_lifetime
            counts[7] += 1
        if fact.latency is not None:
            daily_latencies[key].append(fact.latency)

    # The metrics endpoint only buckets by UTC hour, not by
    # Asia/Ho_Chi_Minh day, so each hourly row is re-bucketed into the same
    # VN calendar day as the ticket facts above before the two are merged --
    # otherwise the token line would silently sit up to 7 hours off the
    # ticket-count/rate lines sharing its x-axis. Sums aggregate correctly
    # across the re-bucketed hours; this is why no percentile is included.
    daily_tokens: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for row in llm_daily_rows:
        arm = row.get("providedModelName")
        time_dimension = row.get("time_dimension")
        if not isinstance(arm, str) or not isinstance(time_dimension, str):
            continue
        try:
            bucket_start = datetime.fromisoformat(time_dimension.replace("Z", "+00:00"))
        except ValueError:
            continue
        key = (bucket_start.astimezone(VIETNAM_TIMEZONE).date().isoformat(), arm)
        tokens = daily_tokens[key]
        tokens[0] += _as_int(row.get("sum_totalTokens"))
        tokens[1] += _as_int(row.get("sum_outputTokens"))

    all_keys = sorted(set(daily_counts) | set(daily_tokens))
    daily = tuple(
        DailyArmPoint(
            date=date_value,
            arm=arm,
            ticket_count=daily_counts[(date_value, arm)][0],
            ai_end_to_end=daily_counts[(date_value, arm)][1],
            ai_first_count=daily_counts[(date_value, arm)][2],
            transferred_count=daily_counts[(date_value, arm)][3],
            direct_cs=daily_counts[(date_value, arm)][4],
            reopen_count=daily_counts[(date_value, arm)][5],
            reopen_denominator=daily_counts[(date_value, arm)][7],
            turn_total=daily_counts[(date_value, arm)][6],
            latency_p50=_percentile(daily_latencies.get((date_value, arm), []), 0.5),
            latency_p95=_percentile(daily_latencies.get((date_value, arm), []), 0.95),
            total_tokens=daily_tokens[(date_value, arm)][0],
            output_tokens=daily_tokens[(date_value, arm)][1],
        )
        for (date_value, arm) in all_keys
    )

    dimension_breakdown: dict[str, tuple[DimensionArmCount, ...]] = {}
    for dimension in DIMENSIONS:
        value_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        value_totals: dict[str, int] = defaultdict(int)
        for fact in facts:
            value = fact.dimension_values[dimension]
            value_counts[(value, fact.arm)][0] += 1
            value_counts[(value, fact.arm)][1] += int(
                fact.outcome == "ai_end_to_end"
            )
            value_totals[value] += 1
        top_values = {
            value
            for value, _count in sorted(
                value_totals.items(), key=lambda item: (-item[1], item[0])
            )[:_TOP_VALUES_PER_DIMENSION]
        }
        dimension_breakdown[dimension] = tuple(
            DimensionArmCount(
                dimension=dimension,
                value=value,
                arm=arm,
                ticket_count=counts[0],
                ai_end_to_end=counts[1],
            )
            for (value, arm), counts in sorted(value_counts.items())
            if value in top_values
        )

    return AbTestSnapshot(
        window_start=window_start,
        window_end=window_end,
        total_tickets=total,
        unmatched_tickets=unmatched,
        arms=tuple(result_arms),
        daily=daily,
        dimensions=dimension_breakdown,
        csat_available=bool(csat_by_ticket),
    )


def default_window(now: datetime) -> tuple[datetime, datetime]:
    """The canonical "current week so far" window, Monday 00:00 VN to now.

    Matches the frontend's own default (`defaultWindowFromReportScope` in
    AbTestSection.tsx) for the common case -- Report Scope defaults to the
    latest single week -- so the background-refreshed cache actually answers
    what most readers see, not an arbitrary unrelated window.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(VIETNAM_TIMEZONE)
    monday = local_now.date() - timedelta(days=local_now.weekday())
    start_local = datetime.combine(monday, datetime.min.time(), tzinfo=VIETNAM_TIMEZONE)
    return start_local.astimezone(timezone.utc), now.astimezone(timezone.utc)


def compute_ab_test(
    client: LangfuseClient,
    window_start: datetime,
    window_end: datetime,
    taxonomy: Taxonomy,
    *,
    csat_by_ticket: Mapping[str, str] | None = None,
    deadline: float | None = None,
    arms: Sequence[str] | None = None,
) -> AbTestSnapshot:
    traces = list(
        client.iter_traces(
            window_start,
            window_end,
            deadline=deadline,
            fields=_TRACE_FIELDS,
        )
    )
    try:
        llm_rows = client.fetch_metrics(
            _llm_metrics_query(window_start, window_end), deadline=deadline
        )
    except Exception:
        # Token/latency aggregates are an enrichment, not the answer. A
        # metrics outage must not blank out the outcome comparison.
        llm_rows = []
    try:
        llm_daily_rows = client.fetch_metrics(
            _llm_metrics_query_hourly(window_start, window_end), deadline=deadline
        )
    except Exception:
        # Daily token lines are an enrichment on top of an enrichment -- a
        # failure here must not blank the (already-optional) window totals.
        llm_daily_rows = []
    try:
        observations_by_name = {
            name: list(
                client.iter_observations_by_name(
                    name, window_start, window_end, deadline=deadline
                )
            )
            for name in _ENRICHMENT_OBSERVATION_NAMES
        }
        trace_enrichment = build_trace_enrichment(observations_by_name, taxonomy)
    except Exception:
        # Skill/Intent breakdown is an enrichment, not the answer. A failed
        # bulk fetch must fall back to "unknown" buckets, not blank the page.
        trace_enrichment = {}
    return aggregate_ab_snapshot(
        traces,
        window_start,
        window_end,
        taxonomy,
        llm_rows=llm_rows,
        llm_daily_rows=llm_daily_rows,
        csat_by_ticket=csat_by_ticket,
        trace_enrichment=trace_enrichment,
        arms=arms,
    )
