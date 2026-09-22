from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as time_of_day, timedelta, timezone
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import time
import threading
from typing import Callable, Mapping, Sequence

from .categories import Taxonomy, load_taxonomy
from .cohort import VIETNAM_TIMEZONE, build_cohort_window
from .enrichment import ENRICHMENT_NAMES, TraceEnrichment, build_trace_enrichment
from .langfuse_client import (
    LangfuseAPIError,
    LangfuseClient,
    LangfuseDeadlineExceeded,
    LangfuseRequestCancelled,
)
from .models import AnalysisResult, CohortWindow, SessionMetrics
from .pipeline import (
    analyze_sessions,
    merge_cached_sessions,
    normalize_raw_traces,
    select_candidate_sessions,
    validate_invariants,
)
from .reopen_shadow import ReopenReasonShadow, pending_shadow, unavailable_shadow


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


_ENRICHMENT_DRAIN_SECONDS = 5.0


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


def _reusable_cached_sessions(
    cached: Mapping[date, Sequence[SessionMetrics]] | None,
    window: CohortWindow,
) -> dict[date, tuple[SessionMetrics, ...]]:
    """Keep only cached weeks this run is allowed to skip fetching.

    A week qualifies when it is inside the reporting window and closed early
    enough that nothing in it can still move: the week that just closed is
    refetched rather than reused, because a session that started in it may
    still be taking turns, and `reopen_within_7d` counts a 168-hour window from
    the first trace. Anything older is settled.
    """
    if not cached:
        return {}
    first_week = window.complete_start_local.date()
    # Exclusive: the most recently closed week is refetched, not reused.
    last_reusable = window.complete_end_exclusive_local.date() - timedelta(weeks=2)
    return {
        week: tuple(sessions)
        for week, sessions in sorted(cached.items())
        if first_week <= week <= last_reusable and sessions
    }


def _fetch_start(
    window: CohortWindow,
    reusable: Mapping[date, Sequence[SessionMetrics]],
) -> datetime:
    """Earliest timestamp this run must ask Langfuse for.

    Starts exactly where the cache stops. No lookback margin is needed here:
    a session whose first trace predates this boundary is recognised by its id
    already being cached, and `_refetch_carried_sessions` then pulls its whole
    trace history by session id. That is both cheaper than widening the window
    by a fixed margin and strictly more correct -- a margin only catches
    sessions that carried over by less than its own length.
    """
    if not reusable:
        return window.query_from_utc
    first_fetched_week = max(reusable) + timedelta(weeks=1)
    start_local = datetime.combine(
        first_fetched_week, time_of_day.min, tzinfo=VIETNAM_TIMEZONE
    )
    return max(start_local.astimezone(timezone.utc), window.query_from_utc)


def _refetch_carried_sessions(
    client: LangfuseClient,
    raw_traces: Sequence[Mapping[str, object]],
    reusable: Mapping[date, Sequence[SessionMetrics]],
) -> tuple[list[Mapping[str, object]], set[str], set[str]]:
    """Pull the full trace history of sessions that carried into this window.

    A ticket opened in a cached week can take another turn later. The narrowed
    fetch sees only that later turn, which on its own would analyze as a brand
    new ticket in the wrong cohort week with a turn count of one. Its session
    id is already in the cache, so it is recognisable: fetch the session whole,
    let it be analyzed from its real first trace, and drop the cached copy it
    supersedes.

    Returns the extra raw traces, the session ids whose cached copies must not
    be merged back in, and the session ids whose partial traces must be dropped
    because their refetch failed -- analyzing those would book the ticket into
    the wrong week, and that wrong copy would then win over the cached one.
    """
    cached_ids = {
        session.session_id
        for sessions in reusable.values()
        for session in sessions
    }
    if not cached_ids:
        return [], set(), set()

    carried = {
        session_id
        for raw in raw_traces
        if isinstance(session_id := raw.get("sessionId"), str)
        and session_id in cached_ids
    }
    extra: list[Mapping[str, object]] = []
    superseded: set[str] = set()
    unresolved: set[str] = set()
    for session_id in sorted(carried):
        try:
            traces = client.list_traces_by_session(session_id)
        except (LangfuseAPIError, ValueError):
            # Fall back to the cached copy: it is a complete analysis of
            # everything up to its own fetch, which beats a partial view built
            # from the later turns alone.
            unresolved.add(session_id)
            continue
        if traces:
            extra.extend(traces)
            superseded.add(session_id)
        else:
            unresolved.add(session_id)
    return extra, superseded, unresolved


def _is_ticket_trace(raw: Mapping[str, object]) -> bool:
    input_data = raw.get("input")
    return (
        isinstance(input_data, Mapping)
        and input_data.get("source") == "ticket"
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
    cached_sessions: Mapping[date, Sequence[SessionMetrics]] | None = None,
) -> ReportRun:
    """Analyze the reporting window, reusing cached closed weeks when given.

    With `cached_sessions`, only the weeks that can still change are fetched
    from Langfuse -- the open week, the week that just closed, and the
    fourteen-day lookback that keeps a session's canonical first trace
    visible. Everything older is folded back in from the cache, which is what
    it already analyzed to. Without it the full window is fetched, exactly as
    before.
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
    reusable = _reusable_cached_sessions(cached_sessions, window)
    # The reporting window stays the full `weeks`; only the Langfuse query
    # narrows. Aggregates are keyed off `window`, so shrinking it here would
    # drop the cached weeks from every breakdown instead of reusing them.
    fetch_from_utc = _fetch_start(window, reusable)
    taxonomy = load_taxonomy(taxonomy_path)
    _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
    enrichment_job = _start_enrichment(
        client,
        # Deliberately NOT narrowed to `fetch_from_utc`. Enrichment lanes are
        # keyed by observation start time, not by the ticket's cohort week, so
        # a ticket opened just before the narrowed boundary would lose the
        # observations that carry its skill and TPE signals -- measured in
        # production as coverage_skill 0.9001 -> 0.8979 and coverage_tpe
        # 0.7701 -> 0.7667 when this used the narrowed bound. Observation lanes
        # are also far cheaper than trace pagination, so widening them back
        # costs little of what the narrowing saves.
        from_start_time=window.query_from_utc,
        to_start_time=window.query_to_utc,
        deadline=enrichment_deadline,
        cancel_event=cancel_event,
        monotonic=monotonic,
    )
    enrichment_finished = False
    try:
        raw_traces = [
            raw
            for raw in client.iter_traces(
                fetch_from_utc,
                window.query_to_utc,
                deadline=refresh_deadline,
                cancel_event=cancel_event,
                max_pages=max_trace_pages,
            )
            if _is_ticket_trace(raw)
        ]
        _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
        carried_traces, superseded, unresolved = _refetch_carried_sessions(
            client, raw_traces, reusable
        )
        if unresolved:
            # Their later turns alone would analyze into the wrong cohort week,
            # and that copy would then take precedence over the correct cached
            # one. Drop them and let the cache stand.
            raw_traces = [
                raw
                for raw in raw_traces
                if raw.get("sessionId") not in unresolved
            ]
        # Ordering is irrelevant: `normalize_raw_traces` deduplicates by trace
        # id and `select_candidate_sessions` sorts each session's turns itself.
        raw_traces.extend(carried_traces)
        _raise_if_refresh_stopped(cancel_event, refresh_deadline, monotonic)
        records, issues, deduplicated_count = normalize_raw_traces(raw_traces)
        selection = select_candidate_sessions(records, issues, window)
        (
            trace_enrichment,
            enrichment_status,
            observations_fetched,
            failed_enrichment_lanes,
        ) = _finish_enrichment(enrichment_job, taxonomy)
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
    if reusable:
        result = merge_cached_sessions(
            result,
            tuple(
                session
                for sessions in reusable.values()
                for session in sessions
                if session.session_id not in superseded
            ),
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
    )


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
) -> tuple[dict[str, TraceEnrichment], str, int, tuple[str, ...]]:
    """Drain all lanes by the shared deadline and discard biased partial data."""
    pending = set(job.futures)
    failed = False
    failed_lanes: set[str] = set()
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
    observations_fetched = sum(len(state.rows) for state in states)
    failed_lanes.update(state.name for state in states if state.error is not None)
    if failed or any(state.error is not None for state in states):
        return {}, "partial", observations_fetched, tuple(sorted(failed_lanes))
    observations = {state.name: state.rows for state in states}
    return (
        build_trace_enrichment(observations, taxonomy),
        "complete",
        observations_fetched,
        (),
    )


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
            state.rows.append(row)
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
