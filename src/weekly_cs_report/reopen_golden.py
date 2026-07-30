from __future__ import annotations

"""Random, blinded golden-set sampling for reopen-reason evaluation."""

import csv
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import random
import secrets
from typing import Callable, Mapping, Protocol, Sequence

from .content_labeler import LabelSet
from .reopen_masker import mask_reopen_text
from .reopen_population import ReopenPopulation, ReopenSession


GOLDEN_CSV_FIELDS = (
    "row_id",
    "initial_user_text",
    "initial_ai_text",
    "followup_user_text",
    "human_label",
)
_DUPLICATE_FRACTION = 0.15


class GoldenSampleError(RuntimeError):
    """Fixed, payload-free golden sampling or artifact failure."""


class _RandomSource(Protocol):
    def sample(self, population: Sequence[object], k: int) -> list[object]:
        ...

    def shuffle(self, values: list[object]) -> None:
        ...


@dataclass(frozen=True)
class GoldenRow:
    row_id: str
    initial_user_text: str = field(repr=False)
    initial_ai_text: str = field(repr=False)
    followup_user_text: str = field(repr=False)
    human_label: str = ""


@dataclass(frozen=True)
class GoldenManifestEntry:
    session_id: str
    anchor_trace_id: str
    followup_trace_id: str
    week: str
    domain: str
    outcome: str
    duplicate_group_id: str | None
    duplicate_source_row_id: str | None


@dataclass(frozen=True)
class GoldenSample:
    labels_version: str
    rows: tuple[GoldenRow, ...]
    manifest: Mapping[str, GoldenManifestEntry]
    duplicate_count: int
    model_denominator: int


def sample_golden(
    population: ReopenPopulation,
    labels: LabelSet,
    *,
    discovery_session_ids: set[str] | frozenset[str],
    n: int,
    rng: _RandomSource | None = None,
    id_factory: Callable[[], str] | None = None,
) -> GoldenSample:
    """Draw one unstratified sample and hide approximately 15% duplicates."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("golden sample size must be positive")
    if not isinstance(labels, LabelSet):
        raise TypeError("labels must be a LabelSet")

    random_source = rng if rng is not None else random.SystemRandom()
    make_id = id_factory if id_factory is not None else _opaque_id
    duplicate_count = min(n // 2, int(n * _DUPLICATE_FRACTION + 0.5))
    model_denominator = n - duplicate_count

    by_session: dict[str, ReopenSession] = {}
    for session in sorted(
        population.sessions,
        key=lambda item: (
            item.session_id,
            item.week,
            item.domain,
            item.outcome,
            item.anchor_trace_id,
            item.followup_trace_id,
        ),
    ):
        if session.session_id not in discovery_session_ids:
            by_session.setdefault(session.session_id, session)
    candidates = tuple(by_session.values())
    if len(candidates) < model_denominator:
        raise GoldenSampleError("golden population is too small")

    selected = tuple(
        random_source.sample(candidates, model_denominator)  # type: ignore[arg-type]
    )
    duplicate_sources = tuple(
        random_source.sample(selected, duplicate_count)  # type: ignore[arg-type]
    )
    duplicate_session_ids = {item.session_id for item in duplicate_sources}

    primary_rows: dict[str, GoldenRow] = {}
    group_ids: dict[str, str] = {}
    used_ids: set[str] = set()
    for session in selected:
        row_id = _next_unique_id(make_id, used_ids)
        primary_rows[session.session_id] = _golden_row(row_id, session)
        if session.session_id in duplicate_session_ids:
            group_ids[session.session_id] = _next_unique_id(make_id, used_ids)

    rows = list(primary_rows.values())
    manifest: dict[str, GoldenManifestEntry] = {}
    for session in selected:
        row = primary_rows[session.session_id]
        manifest[row.row_id] = _manifest_entry(
            session,
            duplicate_group_id=group_ids.get(session.session_id),
            duplicate_source_row_id=None,
        )

    for session in duplicate_sources:
        source = primary_rows[session.session_id]
        row_id = _next_unique_id(make_id, used_ids)
        duplicate = _golden_row(row_id, session)
        rows.append(duplicate)
        manifest[row_id] = _manifest_entry(
            session,
            duplicate_group_id=group_ids[session.session_id],
            duplicate_source_row_id=source.row_id,
        )

    random_source.shuffle(rows)  # type: ignore[arg-type]
    _validate_sample_rows(rows)
    return GoldenSample(
        labels_version=labels.version,
        rows=tuple(rows),
        manifest=manifest,
        duplicate_count=duplicate_count,
        model_denominator=model_denominator,
    )


def load_discovery_session_ids(path: Path) -> frozenset[str]:
    """Load only the discovery session IDs needed for disjoint sampling."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise GoldenSampleError("reopen discovery artifact is unavailable")
    try:
        with source.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or "session_id" not in reader.fieldnames:
                raise GoldenSampleError("reopen discovery artifact is unavailable")
            values = [
                row.get("session_id")
                for row in reader
            ]
    except (OSError, csv.Error):
        raise GoldenSampleError("reopen discovery artifact is unavailable") from None
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise GoldenSampleError("reopen discovery artifact is unavailable")
    return frozenset(values)  # type: ignore[arg-type]


def write_golden_sample(
    output_directory: Path,
    sample: GoldenSample,
) -> tuple[Path, Path]:
    """Write the blinded CSV and separate private manifest at mode 0600."""
    _validate_golden_sample(sample)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or not directory.is_dir():
        raise GoldenSampleError("golden output directory is invalid")
    directory.chmod(0o700)

    csv_path = directory / "golden.csv"
    manifest_path = directory / "golden_manifest.json"
    _write_csv_0600(csv_path, sample.rows)
    _write_json_0600(
        manifest_path,
        {
            "labels_version": sample.labels_version,
            "rows": {
                row_id: {
                    "session_id": entry.session_id,
                    "anchor_trace_id": entry.anchor_trace_id,
                    "followup_trace_id": entry.followup_trace_id,
                    "week": entry.week,
                    "domain": entry.domain,
                    "outcome": entry.outcome,
                    "duplicate_group_id": entry.duplicate_group_id,
                    "duplicate_source_row_id": entry.duplicate_source_row_id,
                }
                for row_id, entry in sample.manifest.items()
            },
        },
    )
    return csv_path, manifest_path


def _golden_row(row_id: str, session: ReopenSession) -> GoldenRow:
    return GoldenRow(
        row_id=row_id,
        initial_user_text=session.initial_user_text,
        initial_ai_text=session.initial_ai_text,
        followup_user_text=session.followup_user_text,
    )


def _manifest_entry(
    session: ReopenSession,
    *,
    duplicate_group_id: str | None,
    duplicate_source_row_id: str | None,
) -> GoldenManifestEntry:
    return GoldenManifestEntry(
        session_id=session.session_id,
        anchor_trace_id=session.anchor_trace_id,
        followup_trace_id=session.followup_trace_id,
        week=session.week.isoformat(),
        domain=session.domain,
        outcome=session.outcome,
        duplicate_group_id=duplicate_group_id,
        duplicate_source_row_id=duplicate_source_row_id,
    )


def _opaque_id() -> str:
    return secrets.token_urlsafe(18)


def _next_unique_id(factory: Callable[[], str], used: set[str]) -> str:
    for _ in range(100):
        value = factory()
        if isinstance(value, str) and value and value not in used:
            used.add(value)
            return value
    raise GoldenSampleError("opaque row id generation failed")


def _validate_sample_rows(rows: Sequence[GoldenRow]) -> None:
    for row in rows:
        if (
            not row.row_id
            or row.human_label != ""
            or not row.initial_user_text
            or not row.initial_ai_text
            or not row.followup_user_text
        ):
            raise GoldenSampleError("golden sample row is invalid")
        for text in (
            row.initial_user_text,
            row.initial_ai_text,
            row.followup_user_text,
        ):
            if mask_reopen_text(text, {}) != text:
                raise GoldenSampleError("golden sample contains unmasked pii")


def _validate_golden_sample(sample: GoldenSample) -> None:
    _validate_sample_rows(sample.rows)
    row_ids = tuple(row.row_id for row in sample.rows)
    if (
        len(row_ids) != len(set(row_ids))
        or set(row_ids) != set(sample.manifest)
        or sample.model_denominator != len(sample.rows) - sample.duplicate_count
    ):
        raise GoldenSampleError("golden sample is invalid")


def _secure_descriptor(path: Path) -> int:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise GoldenSampleError("golden output path is invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    return descriptor


def _write_csv_0600(path: Path, rows: Sequence[GoldenRow]) -> None:
    descriptor = _secure_descriptor(path)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(GOLDEN_CSV_FIELDS))
        writer.writeheader()
        writer.writerows(
            {
                "row_id": row.row_id,
                "initial_user_text": row.initial_user_text,
                "initial_ai_text": row.initial_ai_text,
                "followup_user_text": row.followup_user_text,
                "human_label": "",
            }
            for row in rows
        )


def _write_json_0600(path: Path, payload: Mapping[str, object]) -> None:
    descriptor = _secure_descriptor(path)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
