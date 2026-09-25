from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import time
import threading
from typing import Callable, Mapping, Sequence

from .categories import Taxonomy, load_taxonomy
from .classification import cohort_status_for
from .cohort import build_cohort_window
from .dimension_verifier import is_ticket_trace
from .enrichment import (
    ENRICHMENT_NAMES,
    TraceEnrichment,
    build_trace_enrichment,
    slim_observation,
)
from .langfuse_client import (
    LangfuseAPIError,
    LangfuseClient,
    LangfuseDeadlineExceeded,
    LangfuseRequestCancelled,
)
from .models import (
    AnalysisResult,
    CandidateSelection,
    CohortWindow,
    QualityIssue,
    SessionMetrics,
    TraceRecord,
)
from .pipeline import (
    analyze_sessions,
    merge_cached_sessions,
    normalize_raw_traces,
    select_candidate_sessions,
    validate_invariants,
)
from .reopen_shadow import ReopenReasonShadow, pending_shadow, unavailable_shadow
from .session_cache import SessionCache, cache_fingerprint


@dataclass(frozen=True)
class ReportRun:
    result: AnalysisResult
    taxonomy: Taxonomy
    traces_fetched: int
    traces_deduplicated: int
    enrichment_status: str = "partial"
    observations_fetched: int = 0
    failed_enrichment_lanes: tuple[str, ...] = ()
    reopen_shadow: ReopenReasonShadow = field(default_factory=unavailable_shadow)
    # What the next refresh may reuse. Persist it only when enrichment is
    # complete: a partial run's sessions carry lowered signals.
    session_cache: SessionCache | None = None


_ENRICHMENT_DRAIN_SECONDS = 5.0
# Observations start at their trace's timestamp or later. Sampled 2026-09-25
# over 42,964 observations of 7 days: one led its trace, by 9.6 s.
_ENRICHMENT_MARGIN = timedelta(hours=1)
_ENRICHMENT_NAME_SET = frozenset(ENRICHMENT_NAMES)
_CARRIED_LANE = "carried_trace_observations"
# Langfuse filters traces by their own timestamp, not by when they were
# written, and writes land a little late. Sampled 2026-09-25 (13,645 traces of
# 17 days, 42,964 observations of 7 days): a trace was written at most 1 min
# after its timestamp, an observation at most 8 min after its start. Each
# refresh rereads this much before the previous refresh's reach, so a late
# write is picked up by a later one. Observations appended to a trace days
# after it ran are a different thing; see `_late_written_sessions`.
_REFETCH_OVERLAP = timedelta(hours=2)
# An observation of a trace older than the fetch counts as appended late when
# it starts this long after the fetch start; see `_late_written_sessions`.
_LATE_OBSERVATION_GAP = timedelta(hours=1)
# The safety net for what the overlap cannot see: edits or deletions of older
# traces (sampled 2026-09-25, ~330 ticket traces a week are updated more than
# an hour after their timestamp, for reasons the API does not say).
# ponytail: fixed daily -- one full refresh (~4k requests) per ~96
# incremental ones; stretch it if Langfuse load matters more than drift.
_FULL_REBUILD_EVERY = timedelta(hours=24)
# Carried-session lookups run after the enrichment lanes finish (see
# `_late_written_sessions`), so matching the lanes' 4 workers keeps the peak
# load on Langfuse where it already is. One at a time, they were ~50 s of a
# ~55 s incremental refresh (measured 2026-09-25: 61 lookups at ~1 s each).
_CARRIED_LOOKUP_WORKERS = 4


@dataclass
class _LaneState:
    name: str
    rows: list[dict]
    error: Exception | None = None


@dataclass
class _EnrichmentJob:
    executor: ThreadPoolExecutor
    futures: dict[Future[_LaneState], _LaneState]
    cancel_event: threading.Event
    deadline: float
    monotonic: Callable[[], float]


class _CombinedCancellationEvent(threading.Event):
    def __init__(self, *events: threading.Event) -> None:
        super().__init__()
        self._events = events

    def is_set(self) -> bool:
        return super().is_set() or any(event.is_set() for event in self._events)


def _fetch_start(window: CohortWindow, cache: SessionCache | None) -> datetime:
    """Earliest timestamp this run must ask Langfuse for.

    Everything the previous refresh saw, less the overlap for late writes,
    comes from the cache. A ticket with a new turn is recognised by its session
    id and refetched whole, so nothing older has to be reread -- including the
    open week and the week that just closed. Measured from the cache's own
    reach, so a cache left over from an outage still covers the gap.

    Returns `window.query_from_utc` -- a full refresh -- when there is nothing
    to reuse or the cache is due its daily rebuild.
    """
    if cache is None or window.as_of - cache.built_at > _FULL_REBUILD_EVERY:
        return window.query_from_utc
    return max(cache.fetched_at - _REFETCH_OVERLAP, window.query_from_utc)


def _parsed_timestamp(
    raw: Mapping[str, object], key: str = "timestamp"
) -> datetime | None:
    value = raw.get(key)
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return None if stamp.tzinfo is None else stamp


def _refetch_carried_sessions(
    client: LangfuseClient,
    session_ids: Sequence[str],
    window: CohortWindow,
    cancel_event: threading.Event | None,
    deadline: float,
    monotonic: Callable[[], float],
) -> tuple[list[Mapping[str, object]], set[str]]:
    """Pull the full trace history of sessions that carried into this window.

    A session the cache already knows can take another turn later. The
    narrowed fetch sees only that later turn, which on its own would analyze as
    a brand-new ticket in the wrong cohort week. Fetching the session whole
    lets it be analyzed from its real first trace -- or excluded again, if it
    was invalid or started before the window.

    Only what a full refresh would have seen is kept: ticket traces inside the
    query window. A session id is shared with its chat follow-ups, and one
    chat trace with a bad turn quarantines the whole ticket.

    Returns the traces and the session ids whose lookup failed; their partial
    traces must be dropped so the cached state for them stands.
    """
    def lookup(session_id: str) -> list[dict] | None:
        _raise_if_refresh_stopped(cancel_event, deadline, monotonic)
        try:
            return client.list_traces_by_session(session_id)
        except (LangfuseAPIError, ValueError):
            return None

    extra: list[Mapping[str, object]] = []
    unresolved: set[str] = set()
    for session_id, traces in zip(session_ids, _bounded_map(lookup, session_ids)):
        if traces is None:
            unresolved.add(session_id)
            continue
        kept = [
            raw
            for raw in traces
            if is_ticket_trace(raw)
            and (
                (stamp := _parsed_timestamp(raw)) is None
                or window.query_from_utc <= stamp <= window.query_to_utc
            )
        ]
        if kept:
            extra.extend(kept)
        else:
            unresolved.add(session_id)
    return extra, unresolved


def _session_spans(
    records: Sequence[TraceRecord],
    issues: Sequence[QualityIssue],
) -> dict[str, tuple[datetime, datetime]]:
    """First and last trace timestamp of every session this fetch saw.

    "First" is the canonical first trace -- lowest turn, then time -- exactly as
    `select_candidate_sessions` picks it, because that is what decides whether
    the session started before the window.
    """
    grouped: dict[str, list[TraceRecord]] = {}
    for record in records:
        grouped.setdefault(record.session_id, []).append(record)
    spans = {
        session_id: (
            min(items, key=lambda item: (item.turn, item.timestamp, item.id)).timestamp,
            max(item.timestamp for item in items),
        )
        for session_id, items in grouped.items()
    }
    for issue in issues:
        if issue.session_id is None or issue.timestamp is None:
            continue
        first, last = spans.get(issue.session_id, (issue.timestamp, issue.timestamp))
        if issue.session_id not in grouped:
            first = min(first, issue.timestamp)
        spans[issue.session_id] = (first, max(last, issue.timestamp))
    return spans


def _merge_spans(
    older: Mapping[str, tuple[datetime, datetime]],
    newer: Mapping[str, tuple[datetime, datetime]],
    floor: datetime,
) -> dict[str, tuple[datetime, datetime]]:
    merged = {key: span for key, span in older.items() if span[0] >= floor}
    for key, (first, last) in newer.items():
        if key in merged:
            first = min(first, merged[key][0])
            last = max(last, merged[key][1])
        merged[key] = (first, last)
    return merged


def _merged_selection(
    fresh: CandidateSelection,
    cache: SessionCache,
    reseen: set[str],
    fetch_from_utc: datetime,
) -> CandidateSelection:
    """What a full refresh would have set aside, rebuilt from fresh + cached.

    Cached exclusions stand unless this fetch saw their session again, and only
    while they are still inside the query window a full refresh would read.
    ponytail: an issue without a timestamp cannot be placed in that window and
    is dropped from the cached side; Langfuse always stamps traces.
    """
    window = fresh.window
    floor = window.query_from_utc
    invalid_keyed = list(fresh.invalid_keyed)
    invalid_keyed.extend(
        issue
        for issue in cache.invalid_keyed
        if issue.session_id not in reseen
        and issue.timestamp is not None
        and issue.timestamp >= floor
    )
    fresh_unkeyed = {issue.trace_id for issue in fresh.unkeyed if issue.trace_id}
    unkeyed = list(fresh.unkeyed)
    unkeyed.extend(
        issue
        for issue in cache.unkeyed
        if issue.timestamp is not None
        and floor <= issue.timestamp < fetch_from_utc
        and (issue.trace_id is None or issue.trace_id not in fresh_unkeyed)
    )
    invalid_ids = {issue.session_id for issue in invalid_keyed}
    window_start = window.complete_start_local.astimezone(timezone.utc)
    pre_window = set(fresh.pre_window_start)
    pre_window.update(
        session_id
        for session_id, (first, last) in cache.seen.items()
        if session_id not in reseen
        and session_id not in invalid_ids
        and floor <= first < window_start <= last
    )
    return replace(
        fresh,
        invalid_keyed=tuple(invalid_keyed),
        unkeyed=tuple(unkeyed),
        pre_window_start=tuple(sorted(pre_window)),
    )


def compute_report(
    client: LangfuseClient,
    *,
    as_of: datetime,
    weeks: int,
    include_current_wtd: bool,
    taxonomy_path: Path,
    refresh_timeout_seconds: float = 120.0,
    max_trace_pages: int = 500,
    cancel_event: threading.Event | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    session_cache: SessionCache | None = None,
) -> ReportRun:
    """Analyze the reporting window, reusing a session cache when given.

    With a usable `session_cache`, only the weeks that can still change are
    fetched from Langfuse -- the open week and the week that just closed -- for
    both traces and observations. Sessions the cache already knows that show up
    again are refetched whole by id, and their older traces' observations by
    trace id. Everything older, including what was excluded and why, is folded
    back in from the cache. The contract: the dashboard equals a full refresh.

    The returned `session_cache` is what the next refresh may reuse.
    """
    refresh_start = monotonic()
    refresh_deadline = refresh_start + refresh_timeout_seconds
    # Enrichment runs alongside trace pagination.  A fixed 110-second cap made
    # the result depend on which lane happened to finish last even when the
    # configured refresh deadline still had time left.  Give all lanes the
    # complete shared budget, leaving only the bounded drain period.
    enrichment_deadline = refresh_deadline - _ENRICHMENT_DRAIN_SECONDS
    _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
    window = build_cohort_window(as_of, weeks, include_current_wtd)
    fingerprint = cache_fingerprint(taxonomy_path)
    cache = (
        session_cache
        if session_cache is not None and session_cache.fingerprint == fingerprint
        else None
    )
    # The reporting window stays the full `weeks`; only the Langfuse query
    # narrows. Aggregates are keyed off `window`, so shrinking it here would
    # drop the cached weeks from every breakdown instead of reusing them.
    fetch_from_utc = _fetch_start(window, cache)
    if fetch_from_utc == window.query_from_utc:
        cache = None
    taxonomy = load_taxonomy(taxonomy_path)
    _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
    enrichment_job = _start_enrichment(
        client,
        # Narrowed with the traces: a full-window observation crawl is ~3,500
        # requests per refresh (~350k rows over 13 weeks), the bulk of what a
        # refresh costs Langfuse. Every trace fetched here starts at or after
        # `fetch_from_utc`, so its observations do too (see the margin). The
        # traces that do not -- the older turns of carried sessions -- get
        # their observations by trace id in `_fetch_carried_observations`.
        # Narrowing without that lookup is what once moved coverage_skill
        # 0.9001 -> 0.8979 and coverage_tpe 0.7701 -> 0.7667 in production.
        from_start_time=_enrichment_start(window, fetch_from_utc),
        to_start_time=window.query_to_utc,
        deadline=enrichment_deadline,
        cancel_event=cancel_event,
        monotonic=monotonic,
    )
    enrichment_finished = False
    carried_traces: list[Mapping[str, object]] = []
    try:
        # Ids of chat traces too: their observations are not late writes.
        fetched_ids: set[object] = set()
        raw_traces = []
        for raw in client.iter_traces(
            fetch_from_utc,
            window.query_to_utc,
            deadline=refresh_deadline,
            cancel_event=cancel_event,
            max_pages=max_trace_pages,
        ):
            fetched_ids.add(raw.get("id"))
            if is_ticket_trace(raw):
                raw_traces.append(raw)
        _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
        if cache is not None:
            known = {
                session_id
                for session_id, (first, _last) in cache.seen.items()
                if window.query_from_utc <= first < fetch_from_utc
            }
            carried = sorted({
                session_id
                for raw in raw_traces
                if isinstance(session_id := raw.get("sessionId"), str)
                and session_id in known
            } | _late_written_sessions(
                enrichment_job, fetched_ids, cache, known, fetch_from_utc
            ))
            _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
            carried_traces, unresolved = _refetch_carried_sessions(
                client, carried, window, cancel_event, refresh_deadline, monotonic
            )
            if unresolved:
                # Their later turns alone would analyze into the wrong cohort
                # week, and that copy would then take precedence over the
                # correct cached one. Drop them and let the cache stand.
                raw_traces = [
                    raw
                    for raw in raw_traces
                    if raw.get("sessionId") not in unresolved
                ]
            # Ordering is irrelevant: `normalize_raw_traces` deduplicates by
            # trace id and `select_candidate_sessions` sorts each session's
            # turns itself.
            raw_traces.extend(carried_traces)
        records, issues, deduplicated_count = normalize_raw_traces(raw_traces)
        selection = select_candidate_sessions(records, issues, window)
        _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
        carried_observations = _fetch_carried_observations(
            client,
            # Only tickets that will be analyzed need their signals; a carried
            # session that is excluded again costs no observation requests.
            [
                raw
                for raw in carried_traces
                if raw.get("sessionId") in selection.eligible
            ],
            fetch_from_utc,
            cancel_event,
            refresh_deadline,
            monotonic,
        )
        (
            trace_enrichment,
            enrichment_status,
            observations_fetched,
            failed_enrichment_lanes,
        ) = _finish_enrichment(enrichment_job, taxonomy, carried_observations)
        enrichment_finished = True
        _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
    except BaseException:
        if not enrichment_finished:
            _abort_enrichment(enrichment_job)
        raise
    result = analyze_sessions(
        selection,
        taxonomy,
        trace_enrichment=trace_enrichment,
    )
    validate_invariants(result)
    spans = _session_spans(records, issues)
    trace_sessions = {record.id: record.session_id for record in records}
    if cache is not None:
        # Every session this fetch saw, including ones only an unstamped
        # issue names: for those the fresh analysis is authoritative.
        reseen = set(spans) | {i.session_id for i in issues if i.session_id}
        result = merge_cached_sessions(
            result,
            _reusable_sessions(cache, reseen, fetch_from_utc, window),
            _merged_selection(selection, cache, reseen, fetch_from_utc),
        )
        spans = _merge_spans(cache.seen, spans, window.query_from_utc)
        trace_sessions = {
            **{t: s for t, s in cache.traces.items() if s in spans},
            **trace_sessions,
        }
    next_cache = _next_session_cache(
        result,
        spans,
        trace_sessions,
        fingerprint,
        window,
        built_at=window.query_to_utc if cache is None else cache.built_at,
    )
    _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
    try:
        shadow = pending_shadow(
            Path(__file__).resolve().parents[2] / "config" / "reopen_labels.v1.json"
        )
    except Exception:
        # Shadow failures must never alter the deterministic analysis result.
        shadow = unavailable_shadow()
    return ReportRun(
        result=result,
        taxonomy=taxonomy,
        traces_fetched=len(raw_traces),
        traces_deduplicated=deduplicated_count,
        enrichment_status=enrichment_status,
        observations_fetched=observations_fetched,
        failed_enrichment_lanes=failed_enrichment_lanes,
        reopen_shadow=shadow,
        session_cache=next_cache,
    )


def _reusable_sessions(
    cache: SessionCache,
    reseen: set[str],
    fetch_from_utc: datetime,
    window: CohortWindow,
) -> tuple[SessionMetrics, ...]:
    """Cached tickets this fetch did not see again, restamped for `window`.

    A ticket this fetch saw is analyzed fresh instead. One that opened inside
    the fetch but was not seen is gone from Langfuse, as it would be from a
    full refresh. `cohort_status` and `as_of` are the only fields that depend
    on when the run happens rather than on the traces, so they are recomputed:
    the open week's tickets become complete-week ones on Monday without a
    refetch, and tickets whose week left the window drop out.
    """
    reusable: list[SessionMetrics] = []
    for sessions in cache.weeks.values():
        for session in sessions:
            if (
                session.session_id in reseen
                or session.turn0_timestamp >= fetch_from_utc
            ):
                continue
            status = cohort_status_for(session.turn0_timestamp, window)
            if status in {"complete", "wtd"}:
                reusable.append(
                    replace(session, cohort_status=status, as_of=window.as_of)
                )
    return tuple(reusable)


def _next_session_cache(
    result: AnalysisResult,
    spans: Mapping[str, tuple[datetime, datetime]],
    trace_sessions: Mapping[str, str],
    fingerprint: str,
    window: CohortWindow,
    *,
    built_at: datetime,
) -> SessionCache:
    """The state a later refresh reuses: every ticket in the window.

    The open week is stored too: most of its tickets take no new turn between
    two refreshes, and refetching them is most of what a refresh would cost.
    """
    weeks: dict[date, list[SessionMetrics]] = {}
    for session in result.sessions:
        if session.cohort_status in {"complete", "wtd"}:
            weeks.setdefault(session.cohort_week, []).append(session)
    return SessionCache(
        fingerprint=fingerprint,
        fetched_at=window.query_to_utc,
        built_at=built_at,
        weeks={week: tuple(sessions) for week, sessions in weeks.items()},
        seen=spans,
        traces=trace_sessions,
        invalid_keyed=result.selection.invalid_keyed,
        unkeyed=result.selection.unkeyed,
    )


def _late_written_sessions(
    job: _EnrichmentJob,
    fetched_ids: set[object],
    cache: SessionCache,
    known: set[str],
    fetch_from_utc: datetime,
) -> set[str]:
    """Cached tickets whose older traces took observations since the last fetch.

    Langfuse appends observations to a trace days after it ran, with no new
    turn in the session: sampled 2026-09-25, 27 ticket traces a week, 2-305 h
    after their timestamp, in the TPE/skill/guardrail lanes. The lanes return
    those rows (they filter by start time), but their trace predates the fetch,
    so nothing joins them and the stale cached ticket would stand until the
    daily rebuild. Refetching the session as carried reanalyzes it; the trace
    id to session lookup is local, so it costs no request to find them.

    A row counts only from an hour past `fetch_from_utc`: its trace, older than
    the fetch, then ran over an hour before it, longer than any turn takes. The
    hour also covers rows the previous refresh could not see yet.

    Waits for the lanes, which are small on an incremental refresh. Rows of a
    lane that did not finish are skipped; enrichment fails closed on it anyway.
    """
    wait(job.futures, timeout=max(0.0, job.deadline - job.monotonic()))
    late_from = fetch_from_utc + _LATE_OBSERVATION_GAP
    sessions: set[str] = set()
    for future, state in job.futures.items():
        if not future.done() or state.error is not None:
            continue
        for row in state.rows:
            trace_id = row.get("traceId")
            if not isinstance(trace_id, str) or trace_id in fetched_ids:
                continue
            session_id = cache.traces.get(trace_id)
            if session_id not in known:
                continue
            start = _parsed_timestamp(row, "startTime")
            if start is not None and start >= late_from:
                sessions.add(session_id)
    return sessions


def _enrichment_start(window: CohortWindow, fetch_from_utc: datetime) -> datetime:
    """Earliest observation start time the enrichment lanes must read."""
    return max(fetch_from_utc - _ENRICHMENT_MARGIN, window.query_from_utc)


def _fetch_carried_observations(
    client: LangfuseClient,
    carried_traces: Sequence[Mapping[str, object]],
    fetch_from_utc: datetime,
    cancel_event: threading.Event | None,
    deadline: float,
    monotonic: Callable[[], float],
) -> dict[str, list[dict[str, object]]] | None:
    """Observations of carried traces that predate the narrowed lanes.

    Only a carried session's older turns fall outside the lanes; there are
    few, so one request per trace is far cheaper than widening every lane back
    to the full window. Returns None when a lookup fails, and the caller fails
    enrichment closed exactly as it does for a failed lane: a ticket missing
    its skill/TPE signal would silently lower coverage instead.
    """
    trace_ids = list(dict.fromkeys(
        trace_id
        for raw in carried_traces
        if isinstance(trace_id := raw.get("id"), str)
        and _starts_before(raw, fetch_from_utc)
    ))

    def lookup(trace_id: str) -> list[tuple[str, dict[str, object]]]:
        _raise_if_refresh_stopped(cancel_event, deadline, monotonic)
        # Slimmed in the worker: only the projection outlives the request.
        return [
            (name, slim_observation(observation))
            for observation in client.list_observations(trace_id)
            if (name := observation.get("name")) in _ENRICHMENT_NAME_SET
        ]

    try:
        found = _bounded_map(lookup, trace_ids)
    except LangfuseAPIError:
        return None
    rows: dict[str, list[dict[str, object]]] = {}
    for observations in found:
        for name, observation in observations:
            rows.setdefault(name, []).append(observation)
    return rows


def _bounded_map(function: Callable, items: Sequence) -> list:
    """`function` over `items`, `_CARRIED_LOOKUP_WORKERS` at a time, in order.

    The first error cancels the lookups not yet started and is re-raised once
    the running ones return, so a failure never leaves requests in flight.
    """
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=_CARRIED_LOOKUP_WORKERS) as pool:
        futures = [pool.submit(function, item) for item in items]
        try:
            return [future.result() for future in futures]
        except BaseException:
            for future in futures:
                future.cancel()
            raise


def _starts_before(raw: Mapping[str, object], boundary: datetime) -> bool:
    """True unless the trace provably starts at or after `boundary`."""
    stamp = _parsed_timestamp(raw)
    return stamp is None or stamp < boundary


def _abort_enrichment(job: _EnrichmentJob) -> None:
    """Cooperatively stop and join workers before a core-refresh error escapes."""
    job.cancel_event.set()
    for future in job.futures:
        future.cancel()
    # Every real lane checks the shared cancellation token before/between pages.
    # Joining here prevents a next refresh from overlapping stale GET requests.
    job.executor.shutdown(wait=True, cancel_futures=True)


def _start_enrichment(
    client: LangfuseClient,
    *,
    from_start_time: datetime,
    to_start_time: datetime,
    deadline: float,
    cancel_event: threading.Event | None,
    monotonic: Callable[[], float],
) -> _EnrichmentJob:
    """Start bounded GET-only enrichment while trace pagination is in flight."""
    executor = ThreadPoolExecutor(max_workers=4)
    lane_cancel_event = _CombinedCancellationEvent(
        *(event for event in (cancel_event,) if event is not None)
    )
    states = [_LaneState(name, []) for name in ENRICHMENT_NAMES]
    futures = {
        executor.submit(
            _fetch_enrichment_lane,
            client,
            state,
            from_start_time,
            to_start_time,
            deadline,
            lane_cancel_event,
        ): state
        for state in states
    }
    return _EnrichmentJob(
        executor,
        futures,
        lane_cancel_event,
        deadline,
        monotonic,
    )


def _finish_enrichment(
    job: _EnrichmentJob,
    taxonomy: Taxonomy,
    carried: Mapping[str, Sequence[dict[str, object]]] | None = None,
) -> tuple[dict[str, TraceEnrichment], str, int, tuple[str, ...]]:
    """Drain all lanes by the shared deadline and discard biased partial data.

    `carried` holds per-trace observations of carried sessions' older turns;
    None means that lookup failed and counts as a failed lane.
    """
    pending = set(job.futures)
    failed = carried is None
    failed_lanes: set[str] = {_CARRIED_LANE} if carried is None else set()
    try:
        while pending:
            remaining = job.deadline - job.monotonic()
            if remaining <= 0:
                failed = True
                job.cancel_event.set()
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                failed = True
                failed_lanes.update(job.futures[future].name for future in pending)
                job.cancel_event.set()
                break
            for future in done:
                state = job.futures[future]
                try:
                    future.result()
                except Exception as error:
                    state.error = error
                    job.cancel_event.set()
                    failed_lanes.add(state.name)
                failed = failed or state.error is not None
            if failed:
                job.cancel_event.set()

        if pending:
            for future in pending:
                future.cancel()
            # Cooperative cancellation is checked before and between every
            # observation page; bounded client requests share ``deadline``.
            wait(
                pending,
                timeout=max(
                    0.0,
                    job.deadline + _ENRICHMENT_DRAIN_SECONDS - job.monotonic(),
                ),
            )
        job.executor.shutdown(wait=True, cancel_futures=True)
    except Exception:
        job.cancel_event.set()
        for future in job.futures:
            future.cancel()
        job.executor.shutdown(wait=True, cancel_futures=True)
        failed = True

    states = tuple(job.futures.values())
    observations = {
        state.name: _with_carried(state.rows, (carried or {}).get(state.name, ()))
        for state in states
    }
    observations_fetched = sum(len(rows) for rows in observations.values())
    failed_lanes.update(state.name for state in states if state.error is not None)
    if failed or any(state.error is not None for state in states):
        return {}, "partial", observations_fetched, tuple(sorted(failed_lanes))
    return (
        build_trace_enrichment(observations, taxonomy),
        "complete",
        observations_fetched,
        (),
    )


def _with_carried(
    lane_rows: list[dict],
    carried_rows: Sequence[dict[str, object]],
) -> list[dict]:
    """Lane rows plus carried rows the lane's margin did not already return."""
    if not carried_rows:
        return lane_rows
    seen = {row.get("id") for row in lane_rows}
    return lane_rows + [row for row in carried_rows if row.get("id") not in seen]


def _fetch_enrichment_lane(
    client: LangfuseClient,
    state: _LaneState,
    from_start_time: datetime,
    to_start_time: datetime,
    deadline: float,
    cancel_event: threading.Event,
) -> _LaneState:
    try:
        for row in client.iter_observations_by_name(
            state.name,
            from_start_time,
            to_start_time,
            deadline=deadline,
            cancel_event=cancel_event,
        ):
            if cancel_event.is_set():
                break
            state.rows.append(slim_observation(row))
    except Exception as error:
        state.error = error
        cancel_event.set()
    return state


def _raise_if_refresh_stopped(
    cancel_event: threading.Event | None,
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise LangfuseRequestCancelled("GET", "/api/public/traces")
    if monotonic() >= deadline:
        raise LangfuseDeadlineExceeded("GET", "/api/public/traces")
