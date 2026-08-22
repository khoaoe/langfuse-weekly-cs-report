from __future__ import annotations

"""Discover which models are active and when each first appeared.

`discover_first_seen` reuses the exact `fetch_metrics`/`providedModelName`
shape already proven in `ab_test.py`'s own LLM enrichment
(`_llm_metrics_query_hourly`) -- cheap, since it only needs one model's
earliest hour bucket.

`list_recent_models` deliberately does NOT use that same dimension. Langfuse's
`providedModelName` covers every LLM call logged to the project, including
calls that never answer a ticket (guardrail checks, routing, other sub-steps
inside a ticket's trace). A model that only ever appears in those calls would
still show up as an AB-test candidate and then match zero tickets once
selected, since `ab_test.py` filters tickets by `input.model_info.model_core`
-- a different, already-ticket-scoped field. `list_recent_models` reads that
same field directly off ticket traces, via `_extract_arm`, so every candidate
it offers is guaranteed to have matching ticket data.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Sequence

from .ab_test import _as_int, _extract_arm
from .classification import normalize_trace
from .langfuse_client import LangfuseClient
from .models import QualityIssue

# Expanding backward-looking rounds: cheap first, only paying for a wider
# scan when the model's first occurrence isn't confidently inside a narrower
# one. Four rounds bounds the worst case to four `fetch_metrics` calls.
_LOOKBACK_ROUNDS_DAYS: tuple[int, ...] = (14, 60, 180, 400)
# A candidate found within this margin of the window's start edge might be
# truncated by the window itself, not the model's true first appearance --
# expand and check again rather than trust it.
_EDGE_MARGIN = timedelta(hours=26)
_RECENT_MODELS_LOOKBACK_DAYS = 14


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hourly_count_query(window_start: datetime, window_end: datetime) -> dict:
    return {
        "view": "observations",
        "metrics": [{"measure": "count", "aggregation": "count"}],
        "dimensions": [{"field": "providedModelName"}],
        "fromTimestamp": _iso(window_start),
        "toTimestamp": _iso(window_end),
        "timeDimension": {"granularity": "hour"},
    }


def _earliest_bucket(rows: Sequence[object], model: str) -> datetime | None:
    earliest: datetime | None = None
    for row in rows:
        if not isinstance(row, dict) or row.get("providedModelName") != model:
            continue
        if _as_int(row.get("count_count")) <= 0:
            continue
        bucket = row.get("time_dimension")
        if not isinstance(bucket, str):
            continue
        try:
            parsed = datetime.fromisoformat(bucket.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        parsed = parsed.astimezone(timezone.utc)
        if earliest is None or parsed < earliest:
            earliest = parsed
    return earliest


def discover_first_seen(
    client: LangfuseClient,
    model: str,
    *,
    now: datetime,
    deadline: float | None = None,
) -> tuple[datetime | None, bool]:
    """Earliest hour bucket carrying `model`, searched by expanding window.

    Returns `(first_seen, confirmed)`. `confirmed` is True once a candidate
    sits comfortably inside its window (not flush against the start edge), or
    the widest round has been exhausted -- at that point this is simply the
    best answer the search will ever produce. `confirmed` is False only when
    a Langfuse call itself failed partway through the rounds; the caller
    should retry discovery later rather than trust a partial result forever.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    candidate: datetime | None = None
    for index, lookback_days in enumerate(_LOOKBACK_ROUNDS_DAYS):
        window_start = now - timedelta(days=lookback_days)
        is_last_round = index == len(_LOOKBACK_ROUNDS_DAYS) - 1
        try:
            rows = client.fetch_metrics(
                _hourly_count_query(window_start, now), deadline=deadline
            )
        except Exception:
            return candidate, False
        candidate = _earliest_bucket(rows, model)
        if candidate is None:
            if is_last_round:
                return None, True
            continue
        if is_last_round or candidate - window_start > _EDGE_MARGIN:
            return candidate, True
    return candidate, False


_RECENT_MODELS_TRACE_FIELDS = "core,io"


def list_recent_models(
    client: LangfuseClient,
    *,
    now: datetime,
    lookback_days: int = _RECENT_MODELS_LOOKBACK_DAYS,
    deadline: float | None = None,
) -> list[str]:
    """Ticket-attributed arms with traffic in the recent window, most active
    first -- the candidate list the AB test picker offers.

    Counts distinct tickets per arm (`input.model_info.model_core`), not raw
    trace rows -- a multi-turn ticket must not outweigh a single-turn one.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    window_start = now - timedelta(days=lookback_days)
    tickets_by_arm: dict[str, set[str]] = defaultdict(set)
    for raw in client.iter_traces(
        window_start, now, deadline=deadline, fields=_RECENT_MODELS_TRACE_FIELDS
    ):
        record = normalize_trace(dict(raw))
        if isinstance(record, QualityIssue):
            continue
        arm = _extract_arm(raw.get("input"))
        if arm is None:
            continue
        tickets_by_arm[arm].add(record.session_id)
    ranked = sorted(
        ((arm, len(tickets)) for arm, tickets in tickets_by_arm.items()),
        key=lambda item: (-item[1], item[0]),
    )
    return [arm for arm, _count in ranked]
