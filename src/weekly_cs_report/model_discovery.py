from __future__ import annotations

"""Discover which models are active and when each first appeared.

Both queries reuse the exact `fetch_metrics`/`providedModelName` shape already
proven in `ab_test.py`'s own LLM enrichment (`_llm_metrics_query_hourly`) --
this module just asks a different question of the same endpoint: not "how did
each arm perform this window" but "which arms exist, and since when".
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence

from .ab_test import _as_int
from .langfuse_client import LangfuseClient

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


def list_recent_models(
    client: LangfuseClient,
    *,
    now: datetime,
    lookback_days: int = _RECENT_MODELS_LOOKBACK_DAYS,
    deadline: float | None = None,
) -> list[str]:
    """Model names with observation traffic in the recent window, most
    active first -- the candidate list the AB test picker offers."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    window_start = now - timedelta(days=lookback_days)
    query = {
        "view": "observations",
        "metrics": [{"measure": "count", "aggregation": "count"}],
        "dimensions": [{"field": "providedModelName"}],
        "fromTimestamp": _iso(window_start),
        "toTimestamp": _iso(now),
    }
    rows = client.fetch_metrics(query, deadline=deadline)
    counted: list[tuple[str, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model = row.get("providedModelName")
        if not isinstance(model, str) or not model:
            continue
        counted.append((model, _as_int(row.get("count_count"))))
    counted.sort(key=lambda item: (-item[1], item[0]))
    return [model for model, _count in counted]
