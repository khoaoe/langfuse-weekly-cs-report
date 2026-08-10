from __future__ import annotations

"""Explicit, process-scoped runner for the approved reopen discovery sample."""

import argparse
import csv
from contextlib import contextmanager
import hashlib
import hmac
import io
import json
import os
import stat
import sys
from pathlib import Path
from typing import Sequence

from .cli import (
    ApprovedReopenRunConfig,
    _build_client,
    _parse_as_of,
    load_environment,
    run_sample_reopen,
)
from .llm_client import GemmaHFLLMClient
from .reopen_pii_review import PIIReviewRow
from .reopen_masker import mask_reopen_text


APPROVAL_ENVIRONMENT_NAME = "REOPEN_PII_REVIEW_SHA256"
APPROVED_SEGMENTS = (
    "initial_user_text",
    "initial_ai_text",
    "followup_user_text",
)
PII_REVIEW_FIELDS = (
    "session_id",
    "trace_id",
    "segment",
    "masked_text",
)
MAX_REVIEW_BYTES = 5 * 1024 * 1024
MIN_REVIEW_ROWS = 200
FIXED_ERROR = "controlled sample reopen unavailable"
RUNNER_LOCK_NAME = ".reasons.csv.lock"


class ControlledSampleRunnerError(RuntimeError):
    """Payload-free failure for the controlled PII approval boundary."""


def _positive_weeks(value: str) -> int:
    try:
        weeks = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("weeks must be a positive integer") from error
    if weeks < 1:
        raise argparse.ArgumentTypeError("weeks must be a positive integer")
    return weeks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m weekly_cs_report.reopen_sample_runner"
    )
    parser.add_argument("--approved-review", type=Path, required=True)
    parser.add_argument("--as-of", type=_parse_as_of, required=True)
    parser.add_argument("--weeks", type=_positive_weeks, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _require_secure_directory(directory: Path) -> None:
    try:
        details = os.lstat(directory)
    except OSError as error:
        raise ControlledSampleRunnerError() from error
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ControlledSampleRunnerError()


def _read_secure_review(review: Path) -> bytes:
    try:
        expected = os.lstat(review)
    except OSError as error:
        raise ControlledSampleRunnerError() from error
    if (
        stat.S_ISLNK(expected.st_mode)
        or not stat.S_ISREG(expected.st_mode)
        or stat.S_IMODE(expected.st_mode) != 0o600
        or expected.st_size < 1
        or expected.st_size > MAX_REVIEW_BYTES
    ):
        raise ControlledSampleRunnerError()

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(review, flags)
    except OSError as error:
        raise ControlledSampleRunnerError() from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_dev != expected.st_dev
            or opened.st_ino != expected.st_ino
            or opened.st_size < 1
            or opened.st_size > MAX_REVIEW_BYTES
        ):
            raise ControlledSampleRunnerError()
        chunks: list[bytes] = []
        remaining = MAX_REVIEW_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    except OSError as error:
        raise ControlledSampleRunnerError() from error
    finally:
        os.close(descriptor)
    if not payload or len(payload) > MAX_REVIEW_BYTES:
        raise ControlledSampleRunnerError()
    return payload


def _validate_review_csv(payload: bytes) -> tuple[PIIReviewRow, ...]:
    try:
        text = payload.decode("utf-8")
        reader = csv.reader(io.StringIO(text, newline=""))
        header = tuple(next(reader))
        if header != PII_REVIEW_FIELDS:
            raise ControlledSampleRunnerError()
        seen: set[tuple[str, str, str]] = set()
        rows: list[PIIReviewRow] = []
        for row in reader:
            if len(row) != len(PII_REVIEW_FIELDS):
                raise ControlledSampleRunnerError()
            session_id, trace_id, segment, masked_text = row
            if (
                not session_id.strip()
                or not trace_id.strip()
                or segment not in APPROVED_SEGMENTS
                or not masked_text.strip()
                or mask_reopen_text(masked_text, {}) != masked_text
            ):
                raise ControlledSampleRunnerError()
            identity = (session_id, trace_id, segment)
            if identity in seen:
                raise ControlledSampleRunnerError()
            seen.add(identity)
            rows.append(
                PIIReviewRow(
                    session_id=session_id,
                    trace_id=trace_id,
                    segment=segment,
                    masked_text=masked_text,
                )
            )
        if len(rows) < MIN_REVIEW_ROWS:
            raise ControlledSampleRunnerError()
        return tuple(rows)
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise ControlledSampleRunnerError() from error


def _validate_approval(
    approved_review: Path,
    output_directory: Path,
) -> tuple[PIIReviewRow, ...]:
    review = _absolute_lexical(approved_review)
    output = _absolute_lexical(output_directory)
    if review.name != "pii_review.csv" or review.parent != output:
        raise ControlledSampleRunnerError()
    _require_secure_directory(output)
    payload = _read_secure_review(review)
    expected_digest = os.environ.get(APPROVAL_ENVIRONMENT_NAME)
    if (
        not isinstance(expected_digest, str)
        or len(expected_digest) != 64
        or any(character not in "0123456789abcdef" for character in expected_digest)
        or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_digest)
    ):
        raise ControlledSampleRunnerError()
    return _validate_review_csv(payload)


def _require_absent_reasons(output_directory: Path) -> None:
    try:
        os.lstat(output_directory / "reasons.csv")
    except FileNotFoundError:
        return
    except OSError as error:
        raise ControlledSampleRunnerError() from error
    raise ControlledSampleRunnerError()


@contextmanager
def _hold_runner_lock(output_directory: Path):
    """Hold an exclusive, content-free lock for one output directory run."""
    destination = output_directory / RUNNER_LOCK_NAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(destination, flags, 0o600)
    except OSError as error:
        raise ControlledSampleRunnerError() from error
    owned = None
    try:
        os.fchmod(descriptor, 0o600)
        owned = os.fstat(descriptor)
        if (
            not stat.S_ISREG(owned.st_mode)
            or stat.S_IMODE(owned.st_mode) != 0o600
        ):
            raise ControlledSampleRunnerError()
        yield
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if owned is not None:
            try:
                current = os.lstat(destination)
                if (
                    current.st_dev == owned.st_dev
                    and current.st_ino == owned.st_ino
                ):
                    os.unlink(destination)
            except OSError:
                pass


def _count_reason_rows(output_directory: Path) -> int:
    try:
        with (output_directory / "reasons.csv").open(
            "r", encoding="utf-8", newline=""
        ) as stream:
            reader = csv.reader(stream)
            next(reader)
            return sum(1 for _ in reader)
    except (OSError, UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise ControlledSampleRunnerError() from error


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        approved_review_rows = _validate_approval(
            arguments.approved_review,
            arguments.out,
        )
        with _hold_runner_lock(arguments.out):
            _require_absent_reasons(arguments.out)
            config = ApprovedReopenRunConfig(
                as_of=arguments.as_of,
                weeks=arguments.weeks,
                include_current_wtd=False,
                approved_pii_review_rows=approved_review_rows,
            )
            settings = load_environment()
            with _build_client(settings) as langfuse_client:
                with GemmaHFLLMClient.from_environment(pii_approved=True) as llm_client:
                    run_sample_reopen(
                        config,
                        langfuse_client,
                        llm_client,
                        arguments.out,
                        pii_approved=True,
                    )
            rows = _count_reason_rows(arguments.out)
    except Exception:
        print(FIXED_ERROR, file=sys.stderr)
        return 2
    print(json.dumps({"status": "complete", "rows": rows}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
