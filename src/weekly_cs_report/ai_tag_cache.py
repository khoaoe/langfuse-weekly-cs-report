from __future__ import annotations

"""Strict private cache for Freshdesk `#AI`-tagged ticket discovery.

Structure mirrors entry_coverage_cache.py; the hardened private-file I/O and
validation helpers are imported from there rather than reimplemented.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from types import MappingProxyType

from .entry_coverage_cache import (
    EntryCoverageCacheError,
    _atomic_private_json,
    _DuplicateJSONKey,
    _is_private_owner_file,
    _strict_json_object,
    _validate_monday,
    _validate_utc_timestamp,
)


_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = frozenset({"schema_version", "fetched_weeks", "records"})
_RECORD_KEYS = frozenset({"ticket_id", "opened_at", "cohort_week"})
_TICKET_ID = re.compile(r"[1-9][0-9]{0,19}\Z")


class AiTagCacheError(RuntimeError):
    """A sanitized private-cache contract error."""


@dataclass(frozen=True)
class AiTagRecord:
    ticket_id: str
    opened_at: str
    cohort_week: str

    def __post_init__(self) -> None:
        if not isinstance(self.ticket_id, str) or _TICKET_ID.fullmatch(self.ticket_id) is None:
            raise AiTagCacheError("AI tag cache record is invalid")
        try:
            _validate_utc_timestamp(self.opened_at, "opened timestamp")
            _validate_monday(self.cohort_week, "record cohort week")
        except EntryCoverageCacheError as error:
            raise AiTagCacheError(str(error)) from error


@dataclass(frozen=True)
class AiTagCache:
    fetched_weeks: Mapping[str, str]
    records: tuple[AiTagRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fetched_weeks, Mapping):
            raise AiTagCacheError("AI tag fetched weeks are invalid")
        normalized_weeks: dict[str, str] = {}
        try:
            for week, fetched_at in self.fetched_weeks.items():
                _validate_monday(week, "fetched week")
                _validate_utc_timestamp(fetched_at, "fetched timestamp")
                normalized_weeks[week] = fetched_at
        except EntryCoverageCacheError as error:
            raise AiTagCacheError(str(error)) from error

        try:
            source_records = tuple(self.records)
        except TypeError:
            raise AiTagCacheError("AI tag records are invalid") from None
        if any(not isinstance(item, AiTagRecord) for item in source_records):
            raise AiTagCacheError("AI tag records are invalid")
        ticket_ids = [item.ticket_id for item in source_records]
        if len(ticket_ids) != len(set(ticket_ids)):
            raise AiTagCacheError("AI tag cache contains duplicate tickets")

        object.__setattr__(
            self,
            "fetched_weeks",
            MappingProxyType(dict(sorted(normalized_weeks.items()))),
        )
        object.__setattr__(self, "records", source_records)

    @property
    def fetched_at(self) -> str | None:
        return max(self.fetched_weeks.values(), default=None)


def load_ai_tag_cache(path: Path) -> AiTagCache | None:
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise AiTagCacheError("AI tag cache is invalid") from None
    if not _is_private_owner_file(source_status):
        raise AiTagCacheError("AI tag cache is invalid")

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
            raise AiTagCacheError("AI tag cache is invalid")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            value = json.load(stream, object_pairs_hook=_strict_json_object)
    except AiTagCacheError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJSONKey):
        raise AiTagCacheError("AI tag cache is invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return _cache_from_value(value)


def write_ai_tag_cache(path: Path, cache: AiTagCache) -> None:
    try:
        _atomic_private_json(Path(path), _cache_to_value(cache))
    except EntryCoverageCacheError as error:
        raise AiTagCacheError(str(error)) from error


def _cache_from_value(value: object) -> AiTagCache:
    if not isinstance(value, Mapping) or set(value) != _CACHE_KEYS:
        raise AiTagCacheError("AI tag cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION or isinstance(
        value["schema_version"], bool
    ):
        raise AiTagCacheError("AI tag cache version is invalid")
    raw_weeks = value["fetched_weeks"]
    raw_records = value["records"]
    if not isinstance(raw_weeks, Mapping) or not isinstance(raw_records, list):
        raise AiTagCacheError("AI tag cache is invalid")
    records: list[AiTagRecord] = []
    for item in raw_records:
        if not isinstance(item, Mapping) or set(item) != _RECORD_KEYS:
            raise AiTagCacheError("AI tag cache record is invalid")
        records.append(
            AiTagRecord(
                ticket_id=item["ticket_id"],
                opened_at=item["opened_at"],
                cohort_week=item["cohort_week"],
            )
        )
    return AiTagCache(fetched_weeks=dict(raw_weeks), records=tuple(records))


def _cache_to_value(cache: AiTagCache) -> dict[str, object]:
    if not isinstance(cache, AiTagCache):
        raise AiTagCacheError("AI tag cache is invalid")
    validated = AiTagCache(cache.fetched_weeks, cache.records)
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "fetched_weeks": dict(validated.fetched_weeks),
        "records": [
            {
                "ticket_id": item.ticket_id,
                "opened_at": item.opened_at,
                "cohort_week": item.cohort_week,
            }
            for item in validated.records
        ],
    }
