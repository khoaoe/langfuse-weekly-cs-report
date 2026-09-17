from __future__ import annotations
from .cache_store import (
    atomic_private_json,
    read_private_json,
    validate_monday,
    validate_utc_timestamp,
)

"""Strict private cache for the Freshdesk-to-Langfuse entry comparison."""

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
from typing import Literal


_CACHE_SCHEMA_VERSION = 2
ENTRY_COVERAGE_START_WEEK = "2026-07-06"
_CACHE_KEYS = frozenset({"schema_version", "fetched_weeks", "records"})
_RECORD_KEYS = frozenset(
    {"ticket_id", "opened_at", "cohort_week", "status", "human_replied"}
)
_TICKET_ID = re.compile(r"[1-9][0-9]*\Z")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_ENTRY_STATUSES = frozenset(
    {
        "ai_replied_only",
        "ai_replied_then_transferred",
        "transferred_without_ai_reply",
        "invoked_no_result",
    }
)
EntryCoverageStatus = Literal[
    "ai_replied_only",
    "ai_replied_then_transferred",
    "transferred_without_ai_reply",
    "invoked_no_result",
]


class EntryCoverageCacheError(RuntimeError):
    """A sanitized private-cache contract error."""


@dataclass(frozen=True)
class EntryCoverageRecord:
    ticket_id: str
    opened_at: str
    cohort_week: str
    status: EntryCoverageStatus
    human_replied: bool | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ticket_id, str)
            or _TICKET_ID.fullmatch(self.ticket_id) is None
            or not isinstance(self.status, str)
            or self.status not in _ENTRY_STATUSES
            or (
                self.human_replied is not None
                and not isinstance(self.human_replied, bool)
            )
        ):
            raise EntryCoverageCacheError("Entry coverage cache record is invalid")
        validate_utc_timestamp(self.opened_at, "opened timestamp", EntryCoverageCacheError)
        validate_monday(self.cohort_week, "record cohort week", EntryCoverageCacheError)


@dataclass(frozen=True)
class EntryCoverageCache:
    fetched_weeks: Mapping[str, str]
    records: tuple[EntryCoverageRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fetched_weeks, Mapping):
            raise EntryCoverageCacheError("Entry coverage fetched weeks are invalid")
        normalized_weeks: dict[str, str] = {}
        for week, fetched_at in self.fetched_weeks.items():
            validate_monday(week, "fetched week", EntryCoverageCacheError)
            validate_utc_timestamp(fetched_at, "fetched timestamp", EntryCoverageCacheError)
            normalized_weeks[week] = fetched_at

        try:
            source_records = tuple(self.records)
        except TypeError:
            raise EntryCoverageCacheError("Entry coverage records are invalid") from None
        if any(not isinstance(item, EntryCoverageRecord) for item in source_records):
            raise EntryCoverageCacheError("Entry coverage records are invalid")
        ticket_ids = [item.ticket_id for item in source_records]
        if len(ticket_ids) != len(set(ticket_ids)):
            raise EntryCoverageCacheError("Entry coverage cache contains duplicate tickets")

        object.__setattr__(
            self,
            "fetched_weeks",
            MappingProxyType(dict(sorted(normalized_weeks.items()))),
        )
        object.__setattr__(self, "records", source_records)

    @property
    def fetched_at(self) -> str | None:
        return max(self.fetched_weeks.values(), default=None)


def load_entry_coverage_cache(path: Path) -> EntryCoverageCache | None:
    value = read_private_json(Path(path), EntryCoverageCacheError, "Freshdesk entry coverage cache is invalid")
    if value is None:
        return None
    return _cache_from_value(value)


def write_entry_coverage_cache(path: Path, cache: EntryCoverageCache) -> None:
    atomic_private_json(
        Path(path),
        _cache_to_value(cache),
        EntryCoverageCacheError,
        "Freshdesk entry coverage cache could not be written",
    )


def _cache_from_value(value: object) -> EntryCoverageCache:
    if not isinstance(value, Mapping) or set(value) != _CACHE_KEYS:
        raise EntryCoverageCacheError("Entry coverage cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION or isinstance(
        value["schema_version"], bool
    ):
        raise EntryCoverageCacheError("Entry coverage cache version is invalid")
    raw_weeks = value["fetched_weeks"]
    raw_records = value["records"]
    if not isinstance(raw_weeks, Mapping) or not isinstance(raw_records, list):
        raise EntryCoverageCacheError("Entry coverage cache is invalid")
    records: list[EntryCoverageRecord] = []
    for item in raw_records:
        if not isinstance(item, Mapping) or set(item) != _RECORD_KEYS:
            raise EntryCoverageCacheError("Entry coverage cache record is invalid")
        records.append(
            EntryCoverageRecord(
                ticket_id=item["ticket_id"],
                opened_at=item["opened_at"],
                cohort_week=item["cohort_week"],
                status=item["status"],
                human_replied=item["human_replied"],
            )
        )
    return EntryCoverageCache(fetched_weeks=dict(raw_weeks), records=tuple(records))


def _cache_to_value(cache: EntryCoverageCache) -> dict[str, object]:
    if not isinstance(cache, EntryCoverageCache):
        raise EntryCoverageCacheError("Entry coverage cache is invalid")
    validated = EntryCoverageCache(cache.fetched_weeks, cache.records)
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "fetched_weeks": dict(validated.fetched_weeks),
        "records": [
            {
                "ticket_id": item.ticket_id,
                "opened_at": item.opened_at,
                "cohort_week": item.cohort_week,
                "status": item.status,
                "human_replied": item.human_replied,
            }
            for item in validated.records
        ],
    }

