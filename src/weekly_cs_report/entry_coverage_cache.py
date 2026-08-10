from __future__ import annotations

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


_CACHE_SCHEMA_VERSION = 1
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
        "not_observed_invoked",
        "unresolved",
    }
)
EntryCoverageStatus = Literal[
    "ai_replied_only",
    "ai_replied_then_transferred",
    "transferred_without_ai_reply",
    "invoked_no_result",
    "not_observed_invoked",
    "unresolved",
]


class EntryCoverageCacheError(RuntimeError):
    """A sanitized private-cache contract error."""


class _DuplicateJSONKey(ValueError):
    pass


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
        _validate_utc_timestamp(self.opened_at, "opened timestamp")
        _validate_monday(self.cohort_week, "record cohort week")


@dataclass(frozen=True)
class EntryCoverageCache:
    fetched_weeks: Mapping[str, str]
    records: tuple[EntryCoverageRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fetched_weeks, Mapping):
            raise EntryCoverageCacheError("Entry coverage fetched weeks are invalid")
        normalized_weeks: dict[str, str] = {}
        for week, fetched_at in self.fetched_weeks.items():
            _validate_monday(week, "fetched week")
            _validate_utc_timestamp(fetched_at, "fetched timestamp")
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
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise EntryCoverageCacheError("Entry coverage cache is invalid") from None
    if not _is_private_owner_file(source_status):
        raise EntryCoverageCacheError("Entry coverage cache is invalid")

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
            raise EntryCoverageCacheError("Entry coverage cache is invalid")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            value = json.load(stream, object_pairs_hook=_strict_json_object)
    except EntryCoverageCacheError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJSONKey):
        raise EntryCoverageCacheError("Entry coverage cache is invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return _cache_from_value(value)


def write_entry_coverage_cache(path: Path, cache: EntryCoverageCache) -> None:
    _atomic_private_json(Path(path), _cache_to_value(cache))


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


def _validate_monday(value: object, label: str) -> None:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise EntryCoverageCacheError(f"Entry coverage {label} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise EntryCoverageCacheError(f"Entry coverage {label} is invalid") from None
    if parsed.isoformat() != value or parsed.weekday() != 0:
        raise EntryCoverageCacheError(f"Entry coverage {label} is invalid")
    if value < ENTRY_COVERAGE_START_WEEK:
        raise EntryCoverageCacheError(f"Entry coverage {label} is outside the supported range")


def _validate_utc_timestamp(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise EntryCoverageCacheError(f"Entry coverage {label} is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise EntryCoverageCacheError(f"Entry coverage {label} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise EntryCoverageCacheError(f"Entry coverage {label} is invalid")


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
        raise EntryCoverageCacheError("Entry coverage cache could not be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
