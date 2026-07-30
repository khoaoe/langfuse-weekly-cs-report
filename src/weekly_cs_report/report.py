from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import time
import threading
from typing import Mapping

from .categories import Taxonomy, load_taxonomy
from .cohort import build_cohort_window
from .dimension_backfill import DimensionBackfillStore
from .enrichment import ENRICHMENT_NAMES, TraceEnrichment, build_trace_enrichment
from .langfuse_client import LangfuseClient
from .models import AnalysisResult
from .pipeline import (
    analyze_sessions,
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
    reopen_shadow: ReopenReasonShadow = field(default_factory=unavailable_shadow)


_ENRICHMENT_BUDGET_SECONDS = 110.0
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
) -> ReportRun:
    refresh_deadline = time.monotonic() + _ENRICHMENT_BUDGET_SECONDS
    window = build_cohort_window(as_of, weeks, include_current_wtd)
    taxonomy = load_taxonomy(taxonomy_path)
    enrichment_job = _start_enrichment(
        client,
        from_start_time=window.query_from_utc,
        to_start_time=window.query_to_utc,
        deadline=refresh_deadline,
    )
    enrichment_finished = False
    try:
        raw_traces = [
            raw
            for raw in client.iter_traces(window.query_from_utc, window.query_to_utc)
            if _is_ticket_trace(raw)
        ]
        records, issues, deduplicated_count = normalize_raw_traces(raw_traces)
        selection = select_candidate_sessions(records, issues, window)
        dimension_backfill = _load_private_dimension_backfill()
        trace_enrichment, enrichment_status, observations_fetched = _finish_enrichment(
            enrichment_job,
            taxonomy,
        )
        enrichment_finished = True
    except BaseException:
        if not enrichment_finished:
            _abort_enrichment(enrichment_job)
        raise
    result = analyze_sessions(
        selection,
        taxonomy,
        dimension_backfill=dimension_backfill,
        trace_enrichment=trace_enrichment,
    )
    validate_invariants(result)
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


def _load_private_dimension_backfill() -> Mapping[str, object]:
    """Load P0's mode-0600 overlay without placing it in a dashboard payload."""
    store = DimensionBackfillStore(Path(__file__).resolve().parents[2] / "runtime")
    if not store.path.exists():
        return {}
    return store.load()


def _start_enrichment(
    client: LangfuseClient,
    *,
    from_start_time: datetime,
    to_start_time: datetime,
    deadline: float,
) -> _EnrichmentJob:
    """Start bounded GET-only enrichment while trace pagination is in flight."""
    executor = ThreadPoolExecutor(max_workers=4)
    cancel_event = threading.Event()
    states = [_LaneState(name, []) for name in ENRICHMENT_NAMES]
    futures = {
        executor.submit(
            _fetch_enrichment_lane,
            client,
            state,
            from_start_time,
            to_start_time,
            deadline,
            cancel_event,
        ): state
        for state in states
    }
    return _EnrichmentJob(executor, futures, cancel_event, deadline)


def _finish_enrichment(
    job: _EnrichmentJob,
    taxonomy: Taxonomy,
) -> tuple[dict[str, TraceEnrichment], str, int]:
    """Drain all lanes by the shared deadline and discard biased partial data."""
    pending = set(job.futures)
    failed = False
    try:
        while pending:
            remaining = job.deadline - time.monotonic()
            if remaining <= 0:
                failed = True
                job.cancel_event.set()
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                failed = True
                job.cancel_event.set()
                break
            for future in done:
                state = job.futures[future]
                try:
                    future.result()
                except Exception as error:
                    state.error = error
                    job.cancel_event.set()
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
                timeout=max(0.0, job.deadline + _ENRICHMENT_DRAIN_SECONDS - time.monotonic()),
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
    if failed or any(state.error is not None for state in states):
        return {}, "partial", observations_fetched
    observations = {state.name: state.rows for state in states}
    return (
        build_trace_enrichment(observations, taxonomy),
        "complete",
        observations_fetched,
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
