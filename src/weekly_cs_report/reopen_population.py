from __future__ import annotations

"""Build the server-side population for reopen-reason labeling.

The builder consumes in-memory session metrics and traces.  It never reads a
snapshot or artifact, and it returns only the three approved, masked text
fields instead of retaining raw trace or session objects.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .models import SessionMetrics, TraceRecord
from .reopen_masker import mask_reopen_text


MISSING_REQUIRED_TEXT = "missing_required_text"
_AI_OUTCOMES = frozenset({"ai_end_to_end", "ai_then_cs"})
_KNOWN_META_KEYS = (
    "UserID",
    "App user",
    "TransID",
    "Số điện thoại người dùng",
)


@dataclass(frozen=True)
class ReopenSession:
    session_id: str
    anchor_trace_id: str
    followup_trace_id: str
    week: date
    domain: str
    outcome: str
    initial_user_text: str = field(repr=False)
    initial_ai_text: str = field(repr=False)
    followup_user_text: str = field(repr=False)

    def __post_init__(self) -> None:
        for text in (
            self.initial_user_text,
            self.initial_ai_text,
            self.followup_user_text,
        ):
            if (
                not isinstance(text, str)
                or not text
                or mask_reopen_text(text, {}) != text
            ):
                raise ValueError("reopen session text is not masked")


@dataclass(frozen=True)
class ReopenControl:
    numerator: int
    denominator: int
    rate: float | None


@dataclass(frozen=True)
class ReopenPopulation:
    sessions: tuple[ReopenSession, ...]
    excluded_counts: Mapping[str, int]
    control: ReopenControl


def build_reopen_population(
    sessions: Sequence[SessionMetrics],
    traces_by_session: Mapping[str, Sequence[TraceRecord]],
) -> ReopenPopulation:
    """Build one labeling record per eligible session and direct-CS control."""
    population: list[ReopenSession] = []
    exclusions: Counter[str] = Counter()
    seen_session_ids: set[str] = set()
    control_values: list[int] = []

    for metrics in sessions:
        if metrics.session_id in seen_session_ids:
            continue
        seen_session_ids.add(metrics.session_id)

        if (
            metrics.outcome == "direct_cs"
            and type(metrics.control_reopen_within_7d) is int
            and metrics.control_reopen_within_7d in (0, 1)
        ):
            control_values.append(metrics.control_reopen_within_7d)

        if not _is_labeling_eligible(metrics):
            continue

        raw_traces = traces_by_session.get(metrics.session_id, ())
        ordered = sorted(
            (
                trace
                for trace in raw_traces
                if trace.session_id == metrics.session_id
            ),
            key=lambda trace: (trace.turn, trace.timestamp, trace.id),
        )
        reopen_session = _build_session(metrics, ordered)
        if reopen_session is None:
            exclusions[MISSING_REQUIRED_TEXT] += 1
            continue
        population.append(reopen_session)

    denominator = len(control_values)
    numerator = sum(control_values)
    return ReopenPopulation(
        sessions=tuple(population),
        excluded_counts=dict(exclusions),
        control=ReopenControl(
            numerator=numerator,
            denominator=denominator,
            rate=numerator / denominator if denominator else None,
        ),
    )


def _is_labeling_eligible(metrics: SessionMetrics) -> bool:
    return (
        metrics.ai_first is True
        and metrics.reopen_within_7d == 1
        and metrics.outcome in _AI_OUTCOMES
        and metrics.data_quality == "valid"
    )


def _build_session(
    metrics: SessionMetrics,
    ordered: Sequence[TraceRecord],
) -> ReopenSession | None:
    if not ordered:
        return None
    first = ordered[0]
    followup = next(
        (
            trace
            for trace in ordered[1:]
            if timedelta() < trace.timestamp - first.timestamp <= timedelta(hours=168)
        ),
        None,
    )
    if followup is None:
        return None

    initial_user_text = _mapping_text(first.input_data, "user_input")
    initial_ai_text = _mapping_text(first.output_data, "response")
    followup_user_text = _mapping_text(followup.input_data, "user_input")
    if (
        initial_user_text is None
        or initial_ai_text is None
        or followup_user_text is None
    ):
        return None

    known_meta = _known_meta_by_trace(ordered)
    return ReopenSession(
        session_id=metrics.session_id,
        anchor_trace_id=first.id,
        followup_trace_id=followup.id,
        week=metrics.cohort_week,
        domain=metrics.dimensions.issue_category,
        outcome=metrics.outcome,
        initial_user_text=_mask_with_all_meta(initial_user_text, known_meta),
        initial_ai_text=_mask_with_all_meta(initial_ai_text, known_meta),
        followup_user_text=_mask_with_all_meta(followup_user_text, known_meta),
    )


def _mapping_text(value: object, key: str) -> str | None:
    if not isinstance(value, Mapping):
        return None
    text = value.get(key)
    if not isinstance(text, str) or not text.strip():
        return None
    return text


def _known_meta_by_trace(
    traces: Sequence[TraceRecord],
) -> tuple[Mapping[str, object], ...]:
    known_meta: list[Mapping[str, object]] = []
    for trace in traces:
        if not isinstance(trace.input_data, Mapping):
            continue
        other_info = trace.input_data.get("other_info")
        if not isinstance(other_info, Mapping):
            continue
        meta = other_info.get("meta")
        if not isinstance(meta, Mapping):
            continue
        approved = {
            key: meta[key]
            for key in _KNOWN_META_KEYS
            if key in meta
        }
        if approved:
            known_meta.append(approved)
    return tuple(known_meta)


def _mask_with_all_meta(
    text: str,
    known_meta: Sequence[Mapping[str, object]],
) -> str:
    masked = text
    if not known_meta:
        return mask_reopen_text(masked, {})
    for meta in known_meta:
        masked = mask_reopen_text(masked, meta)
    return masked
