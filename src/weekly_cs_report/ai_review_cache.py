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
from .cache_store import (
    atomic_private_json,
    read_private_json,
    validate_monday,
    validate_utc_timestamp,
)


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


@dataclass(frozen=True)
class AIReviewCache:
    fetched_weeks: Mapping[str, str]
    records: tuple[AIReviewRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fetched_weeks, Mapping):
            raise AIReviewCacheError("AI review fetched weeks are invalid")
        normalized_weeks: dict[str, str] = {}
        for week, fetched_at in self.fetched_weeks.items():
            validate_monday(week, "fetched week", AIReviewCacheError)
            validate_utc_timestamp(
                fetched_at, "fetched timestamp", AIReviewCacheError
            )
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
    value = read_private_json(
        Path(path), AIReviewCacheError, "AI review cache is invalid"
    )
    if value is None:
        return None
    return _cache_from_value(value)


def write_ai_review_cache(path: Path, cache: AIReviewCache) -> None:
    atomic_private_json(
        Path(path),
        _cache_to_value(cache),
        AIReviewCacheError,
        "AI review cache could not be written",
    )


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

