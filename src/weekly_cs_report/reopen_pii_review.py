from __future__ import annotations

"""Server-side export for the mandatory reopen-labeling PII review gate."""

import csv
from dataclasses import dataclass, field
import os
from pathlib import Path

from .reopen_masker import mask_reopen_text
from .reopen_population import ReopenPopulation, ReopenSession


PII_REVIEW_LIMIT = 200
PII_REVIEW_FIELDS = (
    "session_id",
    "trace_id",
    "segment",
    "masked_text",
)
_SEGMENTS = (
    "initial_user_text",
    "initial_ai_text",
    "followup_user_text",
)


class PIIReviewError(RuntimeError):
    """Fixed, payload-free failure at the manual PII review boundary."""


@dataclass(frozen=True)
class PIIReviewRow:
    session_id: str
    trace_id: str
    segment: str
    masked_text: str = field(repr=False)


def build_pii_review_rows(
    population: ReopenPopulation,
    *,
    limit: int = PII_REVIEW_LIMIT,
) -> tuple[PIIReviewRow, ...]:
    """Select a stable, balanced sample across the three approved segments."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("PII review limit must be a non-negative integer")
    bounded_limit = min(limit, PII_REVIEW_LIMIT)
    if bounded_limit == 0:
        return ()
    ordered = sorted(
        population.sessions,
        key=lambda item: (
            item.session_id,
            item.week,
            item.domain,
            item.outcome,
            item.anchor_trace_id,
            item.followup_trace_id,
        ),
    )
    rows: list[PIIReviewRow] = []
    for session in ordered:
        for segment in _SEGMENTS:
            rows.append(_review_row(session, segment))
            if len(rows) == bounded_limit:
                return tuple(rows)
    return tuple(rows)


def write_pii_review_csv(
    output_directory: Path,
    population: ReopenPopulation,
) -> Path:
    """Write only allowlisted scalar fields to a mode-0600 review artifact."""
    rows = build_pii_review_rows(population)
    _validate_rows(rows)

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or not directory.is_dir():
        raise PIIReviewError("pii review output directory is invalid")
    directory.chmod(0o700)

    destination = directory / "pii_review.csv"
    if destination.exists() and (
        destination.is_symlink() or not destination.is_file()
    ):
        raise PIIReviewError("pii review output path is invalid")

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=list(PII_REVIEW_FIELDS))
            writer.writeheader()
            writer.writerows(
                {
                    "session_id": row.session_id,
                    "trace_id": row.trace_id,
                    "segment": row.segment,
                    "masked_text": row.masked_text,
                }
                for row in rows
            )
    finally:
        if destination.exists() and not destination.is_symlink():
            destination.chmod(0o600)
    return destination


def _review_row(session: ReopenSession, segment: str) -> PIIReviewRow:
    trace_id = (
        session.followup_trace_id
        if segment == "followup_user_text"
        else session.anchor_trace_id
    )
    text = getattr(session, segment)
    return PIIReviewRow(
        session_id=session.session_id,
        trace_id=trace_id,
        segment=segment,
        masked_text=text,
    )


def _validate_rows(rows: tuple[PIIReviewRow, ...]) -> None:
    for row in rows:
        if (
            not row.session_id
            or not row.trace_id
            or row.segment not in _SEGMENTS
            or not row.masked_text
        ):
            raise PIIReviewError("pii review row is invalid")
        # Population has already masked exact values from the four approved
        # meta keys.  Re-running the pattern masker here catches any
        # deterministic pattern that could otherwise reach the review file.
        if mask_reopen_text(row.masked_text, {}) != row.masked_text:
            raise PIIReviewError("pii review contains unmasked pii")
