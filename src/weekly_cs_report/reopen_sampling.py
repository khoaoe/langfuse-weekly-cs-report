from __future__ import annotations

"""Deterministic, server-side discovery sampling for reopen reasons.

Only ``ReopenSession.followup_user_text`` enters embedding.  The other two
already-masked segments are used solely to request one free-text reason for a
selected session.  Clusters are a sampling stratum, never labels.
"""

import csv
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from math import sqrt
import os
from pathlib import Path
from typing import Mapping

from .llm_client import LLMClient
from .reopen_masker import mask_reopen_text
from .reopen_population import ReopenSession


DISCOVERY_BATCH_SIZE = 50
DISCOVERY_SAMPLE_CAP = 300
MAX_REASON_TEXT_LENGTH = 500
_MIN_CLUSTERS = 5
_MAX_CLUSTERS = 15
_CSV_FIELDS = (
    "session_id",
    "week",
    "domain",
    "outcome",
    "cluster_id",
    "reason_text",
)


class ReopenSamplingError(RuntimeError):
    """Fixed, payload-free error for discovery sampling failures."""


@dataclass(frozen=True)
class DiscoveryRow:
    session_id: str
    week: str
    domain: str
    outcome: str
    cluster_id: int
    reason_text: str = field(repr=False)


@dataclass(frozen=True)
class ReopenDiscovery:
    rows: tuple[DiscoveryRow, ...]
    clustered_sessions: tuple[ReopenSession, ...] = field(repr=False)
    cluster_ids: tuple[int, ...]
    cluster_count: int
    silhouette_score: float | None
    attempted_cluster_counts: tuple[int, ...]
    generation_batch_count: int


def sample_reopen(
    sessions: Sequence[ReopenSession],
    llm_client: LLMClient,
) -> ReopenDiscovery:
    """Embed followups, cluster deterministically, then sample each stratum.

    A discovery round keeps one deterministic session per populated
    ``week × domain × outcome × cluster`` stratum before repeating a stratum.
    Reason generations are processed in groups of 50 and stop only after two
    consecutive batches add no normalized reason, subject to a 300-session
    cap.  A population whose required first round exceeds that cap fails
    rather than silently omitting a stratum.
    """
    ordered = tuple(
        sorted(
            sessions,
            key=lambda item: (item.week, item.domain, item.outcome, item.session_id),
        )
    )
    if len({item.session_id for item in ordered}) != len(ordered):
        raise ReopenSamplingError("reopen discovery sessions must be unique")
    if not ordered:
        return ReopenDiscovery((), (), (), 0, None, (), 0)

    # This is deliberately the only field supplied to the embedding method.
    embedding_result = llm_client.embed(tuple(item.followup_user_text for item in ordered))
    vectors = _normalized_vectors(embedding_result.vectors, expected_count=len(ordered))
    cluster_ids, cluster_count, silhouette_score, attempted = _select_clusters(vectors)
    selected, stratum_count = _round_robin_selection(ordered, cluster_ids)
    if stratum_count > DISCOVERY_SAMPLE_CAP:
        raise ReopenSamplingError("reopen discovery stratum limit exceeded")

    rows: list[DiscoveryRow] = []
    seen_reasons: set[str] = set()
    consecutive_empty_reason_batches = 0
    generation_batch_count = 0
    for batch in _batches(selected[:DISCOVERY_SAMPLE_CAP], DISCOVERY_BATCH_SIZE):
        generation_batch_count += 1
        batch_has_new_reason = False
        for index in batch:
            session = ordered[index]
            generated = llm_client.generate_structured(
                messages=(_REASON_INSTRUCTION, _reason_message(session)),
                response_schema=_REASON_RESPONSE_SCHEMA,
            )
            reason_text = mask_reopen_text(_reason_text(generated.value), {})
            normalized_reason = " ".join(reason_text.split()).casefold()
            if normalized_reason not in seen_reasons:
                seen_reasons.add(normalized_reason)
                batch_has_new_reason = True
            rows.append(
                DiscoveryRow(
                    session_id=session.session_id,
                    week=session.week.isoformat(),
                    domain=session.domain,
                    outcome=session.outcome,
                    cluster_id=cluster_ids[index],
                    # Defense in depth: no generated output bypasses the
                    # approved deterministic pattern masker before artifact IO.
                    reason_text=reason_text,
                )
            )
        if batch_has_new_reason:
            consecutive_empty_reason_batches = 0
        else:
            consecutive_empty_reason_batches += 1
        # The first round is the prefix of ``selected`` by construction, so
        # saturation cannot suppress a non-empty stratum.
        if (
            len(rows) >= stratum_count
            and consecutive_empty_reason_batches >= 2
        ):
            break

    return ReopenDiscovery(
        rows=tuple(rows),
        clustered_sessions=ordered,
        cluster_ids=cluster_ids,
        cluster_count=cluster_count,
        silhouette_score=silhouette_score,
        attempted_cluster_counts=attempted,
        generation_batch_count=generation_batch_count,
    )


_REASON_RESPONSE_SCHEMA: Mapping[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "reopen_discovery_reason",
        "schema": {
            "type": "object",
            "properties": {"reason_text": {"type": "string"}},
            "required": ["reason_text"],
            "additionalProperties": False,
        },
    },
}

_REASON_INSTRUCTION: Mapping[str, object] = {
    "role": "system",
    "content": (
        "Trả về đúng một câu lý do khách quay lại. Không đưa bất kỳ định danh "
        "session, trace, ticket, khách hàng, hoặc giao dịch nào."
    ),
}


def _reason_message(session: ReopenSession) -> Mapping[str, object]:
    # The three values are already deterministically masked in reopen_population.
    return {
        "role": "user",
        "content": {
            "initial_user_text": session.initial_user_text,
            "initial_ai_text": session.initial_ai_text,
            "followup_user_text": session.followup_user_text,
        },
    }


def _reason_text(value: Mapping[str, object]) -> str:
    reason = value.get("reason_text")
    if not isinstance(reason, str) or not reason.strip():
        raise ReopenSamplingError("reopen discovery response is invalid")
    return " ".join(reason.split())[:MAX_REASON_TEXT_LENGTH]


def _normalized_vectors(
    vectors: Sequence[Sequence[float]], *, expected_count: int
) -> tuple[tuple[float, ...], ...]:
    if len(vectors) != expected_count or not vectors:
        raise ReopenSamplingError("reopen embedding response is invalid")
    dimensions = len(vectors[0])
    if dimensions < 1:
        raise ReopenSamplingError("reopen embedding response is invalid")
    normalized: list[tuple[float, ...]] = []
    for vector in vectors:
        if len(vector) != dimensions or any(not isinstance(value, (int, float)) for value in vector):
            raise ReopenSamplingError("reopen embedding response is invalid")
        length = sqrt(sum(float(value) * float(value) for value in vector))
        normalized.append(
            tuple(float(value) / length for value in vector)
            if length
            else tuple(0.0 for _ in vector)
        )
    return tuple(normalized)


def _select_clusters(
    vectors: Sequence[tuple[float, ...]],
) -> tuple[tuple[int, ...], int, float | None, tuple[int, ...]]:
    # Silhouette is undefined below six items because the specified k range
    # starts at five and requires at least one point outside every cluster.
    if len(vectors) < _MIN_CLUSTERS + 1:
        return tuple(0 for _ in vectors), 1, None, ()

    candidates = tuple(range(_MIN_CLUSTERS, min(_MAX_CLUSTERS, len(vectors) - 1) + 1))
    best: tuple[float, int, tuple[int, ...]] | None = None
    for cluster_count in candidates:
        assignments = _kmeans_cosine(vectors, cluster_count)
        # Degenerate centroids make fewer real clusters than the candidate;
        # such a result is not eligible to represent that k in silhouette
        # selection or in the reported cluster count.
        if len(set(assignments)) != cluster_count:
            continue
        score = _silhouette_score(vectors, assignments)
        if score is None:
            continue
        candidate = (score, cluster_count, assignments)
        if best is None or candidate[0] > best[0] or (
            candidate[0] == best[0] and candidate[1] < best[1]
        ):
            best = candidate
    if best is None:
        return tuple(0 for _ in vectors), 1, None, candidates
    return best[2], best[1], best[0], candidates


def _kmeans_cosine(
    vectors: Sequence[tuple[float, ...]], cluster_count: int
) -> tuple[int, ...]:
    centroids = list(vectors[:cluster_count])
    assignments: tuple[int, ...] | None = None
    for _ in range(50):
        next_assignments = tuple(
            min(
                range(cluster_count),
                key=lambda cluster_id: (_cosine_distance(vector, centroids[cluster_id]), cluster_id),
            )
            for vector in vectors
        )
        if next_assignments == assignments:
            break
        assignments = next_assignments
        updated: list[tuple[float, ...]] = []
        for cluster_id, centroid in enumerate(centroids):
            members = [
                vector
                for vector, assigned_cluster in zip(vectors, assignments)
                if assigned_cluster == cluster_id
            ]
            updated.append(_unit_mean(members) if members else centroid)
        centroids = updated
    return assignments if assignments is not None else ()


def _silhouette_score(
    vectors: Sequence[tuple[float, ...]], assignments: Sequence[int]
) -> float | None:
    members: dict[int, list[int]] = defaultdict(list)
    for index, cluster_id in enumerate(assignments):
        members[cluster_id].append(index)
    if len(members) < 2:
        return None
    scores: list[float] = []
    for index, cluster_id in enumerate(assignments):
        own = members[cluster_id]
        if len(own) == 1:
            scores.append(0.0)
            continue
        within = sum(_cosine_distance(vectors[index], vectors[other]) for other in own if other != index)
        a = within / (len(own) - 1)
        b = min(
            sum(_cosine_distance(vectors[index], vectors[other]) for other in other_members)
            / len(other_members)
            for other_cluster, other_members in members.items()
            if other_cluster != cluster_id
        )
        scores.append((b - a) / max(a, b) if max(a, b) else 0.0)
    return sum(scores) / len(scores)


def _unit_mean(vectors: Sequence[tuple[float, ...]]) -> tuple[float, ...]:
    mean = tuple(sum(vector[index] for vector in vectors) / len(vectors) for index in range(len(vectors[0])))
    length = sqrt(sum(value * value for value in mean))
    return tuple(value / length for value in mean) if length else tuple(0.0 for _ in mean)


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    return 1.0 - sum(a * b for a, b in zip(left, right))


def _round_robin_selection(
    sessions: Sequence[ReopenSession], cluster_ids: Sequence[int]
) -> tuple[tuple[int, ...], int]:
    by_stratum: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for index, (session, cluster_id) in enumerate(zip(sessions, cluster_ids)):
        stratum = (session.week, session.domain, session.outcome, cluster_id)
        by_stratum[stratum].append(index)
    ordered_strata = tuple(sorted(by_stratum))
    selected: list[int] = []
    round_index = 0
    while True:
        added = False
        for stratum in ordered_strata:
            members = by_stratum[stratum]
            if round_index < len(members):
                selected.append(members[round_index])
                added = True
        if not added:
            return tuple(selected), len(ordered_strata)
        round_index += 1


def _batches(values: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def write_reopen_discovery_csv(
    output_directory: Path,
    rows: Sequence[DiscoveryRow],
) -> Path:
    """Write the only discovery artifact with server-side-only permissions."""
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or not directory.is_dir():
        raise ReopenSamplingError("reopen discovery output directory is invalid")
    directory.chmod(0o700)
    destination = directory / "reasons.csv"
    if destination.exists() and (destination.is_symlink() or not destination.is_file()):
        raise ReopenSamplingError("reopen discovery output path is invalid")

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(_CSV_FIELDS))
            writer.writeheader()
            writer.writerows(
                {
                    "session_id": row.session_id,
                    "week": row.week,
                    "domain": row.domain,
                    "outcome": row.outcome,
                    "cluster_id": row.cluster_id,
                    "reason_text": row.reason_text,
                }
                for row in rows
            )
    finally:
        if destination.exists() and not destination.is_symlink():
            destination.chmod(0o600)
    return destination
