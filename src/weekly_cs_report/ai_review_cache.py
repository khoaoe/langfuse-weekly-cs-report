from __future__ import annotations

"""Strict private cache for Freshdesk AI post-review (hậu kiểm) records."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from types import MappingProxyType

from .ai_review import AIReviewError, AIReviewRecord


_CACHE_SCHEMA_VERSION = 1
AI_REVIEW_START_WEEK = "2026-06-29"
_CACHE_KEYS = frozenset({"schema_version", "fetched_weeks", "records"})
_RECORD_KEYS = frozenset(
    {
        "ticket_id",
        "opened_at",
        "cohort_week",
        "rating",
        "review_count",
        "review_date",
        "reopen_replied",
        "reopen_reply_count",
        "user_replied",
    }
)
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class AIReviewCacheError(RuntimeError):
    """A sanitized AI-review private-cache contract error."""


class _DuplicateJSONKey(ValueError):
    pass


@dataclass(frozen=True)
class AIReviewCache:
    fetched_weeks: Mapping[str, str]
    records: tuple[AIReviewRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fetched_weeks, Mapping):
            raise AIReviewCacheError("AI review fetched weeks are invalid")
        normalized_weeks: dict[str, str] = {}
        for week, fetched_at in self.fetched_weeks.items():
            _validate_monday(week, "fetched week")
            _validate_utc_timestamp(fetched_at, "fetched timestamp")
            normalized_weeks[week] = fetched_at

        try:
            source_records = tuple(self.records)
        except TypeError:
            raise AIReviewCacheError("AI review records are invalid") from None
        if any(not isinstance(item, AIReviewRecord) for item in source_records):
            raise AIReviewCacheError("AI review records are invalid")
        ticket_ids = [item.ticket_id for item in source_records]
        if len(ticket_ids) != len(set(ticket_ids)):
            raise AIReviewCacheError("AI review cache contains duplicate tickets")

        object.__setattr__(
            self,
            "fetched_weeks",
            MappingProxyType(dict(sorted(normalized_weeks.items()))),
        )
        object.__setattr__(self, "records", source_records)

    @property
    def fetched_at(self) -> str | None:
        return max(self.fetched_weeks.values(), default=None)


def load_ai_review_cache(path: Path) -> AIReviewCache | None:
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise AIReviewCacheError("AI review cache is invalid") from None
    if not _is_private_owner_file(source_status):
        raise AIReviewCacheError("AI review cache is invalid")

    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        opened_status = os.fstat(descriptor)
        if (
            not _is_private_owner_file(opened_status)
            or source_status.st_dev != opened_status.st_dev
            or source_status.st_ino != opened_status.st_ino
        ):
            raise AIReviewCacheError("AI review cache is invalid")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            value = json.load(stream, object_pairs_hook=_strict_json_object)
    except AIReviewCacheError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJSONKey):
        raise AIReviewCacheError("AI review cache is invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return _cache_from_value(value)


def write_ai_review_cache(path: Path, cache: AIReviewCache) -> None:
    _atomic_private_json(Path(path), _cache_to_value(cache))


def _cache_from_value(value: object) -> AIReviewCache:
    if not isinstance(value, Mapping) or set(value) != _CACHE_KEYS:
        raise AIReviewCacheError("AI review cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION or isinstance(
        value["schema_version"], bool
    ):
        raise AIReviewCacheError("AI review cache version is invalid")
    raw_weeks = value["fetched_weeks"]
    raw_records = value["records"]
    if not isinstance(raw_weeks, Mapping) or not isinstance(raw_records, list):
        raise AIReviewCacheError("AI review cache is invalid")
    records: list[AIReviewRecord] = []
    for item in raw_records:
        if not isinstance(item, Mapping) or set(item) != _RECORD_KEYS:
            raise AIReviewCacheError("AI review cache record is invalid")
        try:
            records.append(
                AIReviewRecord(
                    ticket_id=item["ticket_id"],
                    opened_at=item["opened_at"],
                    cohort_week=item["cohort_week"],
                    rating=item["rating"],
                    review_count=item["review_count"],
                    review_date=item["review_date"],
                    reopen_replied=item["reopen_replied"],
                    reopen_reply_count=item["reopen_reply_count"],
                    user_replied=item["user_replied"],
                )
            )
        except AIReviewError:
            raise AIReviewCacheError("AI review cache record is invalid") from None
    return AIReviewCache(fetched_weeks=dict(raw_weeks), records=tuple(records))


def _cache_to_value(cache: AIReviewCache) -> dict[str, object]:
    if not isinstance(cache, AIReviewCache):
        raise AIReviewCacheError("AI review cache is invalid")
    validated = AIReviewCache(cache.fetched_weeks, cache.records)
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "fetched_weeks": dict(validated.fetched_weeks),
        "records": [
            {
                "ticket_id": item.ticket_id,
                "opened_at": item.opened_at,
                "cohort_week": item.cohort_week,
                "rating": item.rating,
                "review_count": item.review_count,
                "review_date": item.review_date,
                "reopen_replied": item.reopen_replied,
                "reopen_reply_count": item.reopen_reply_count,
                "user_replied": item.user_replied,
            }
            for item in validated.records
        ],
    }


def _validate_monday(value: object, label: str) -> None:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise AIReviewCacheError(f"AI review {label} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AIReviewCacheError(f"AI review {label} is invalid") from None
    if parsed.isoformat() != value or parsed.weekday() != 0:
        raise AIReviewCacheError(f"AI review {label} is invalid")
    if value < AI_REVIEW_START_WEEK:
        raise AIReviewCacheError(f"AI review {label} is outside the supported range")


def _validate_utc_timestamp(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise AIReviewCacheError(f"AI review {label} is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise AIReviewCacheError(f"AI review {label} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AIReviewCacheError(f"AI review {label} is invalid")


def _is_private_owner_file(details: os.stat_result) -> bool:
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_uid == os.geteuid()
        and stat.S_IMODE(details.st_mode) == 0o600
    )


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _atomic_private_json(path: Path, payload: object) -> None:
    directory = path.parent
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        if not directory.exists():
            directory.mkdir(mode=0o700, parents=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=directory
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError:
        raise AIReviewCacheError("AI review cache could not be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
