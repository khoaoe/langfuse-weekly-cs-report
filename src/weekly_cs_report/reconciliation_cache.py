from __future__ import annotations

"""Strict private disk contract for derived Freshdesk outcome reconciliation."""

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


_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = frozenset({"schema_version", "fetched_weeks", "records"})
_RECORD_KEYS = frozenset(
    {"ticket_id", "cohort_week", "human_replied_after_ai"}
)
_TICKET_ID = re.compile(r"[1-9][0-9]*\Z")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class ReconciliationCacheError(RuntimeError):
    """A sanitized private-cache contract error."""


class _DuplicateJSONKey(ValueError):
    pass


@dataclass(frozen=True)
class ReconciliationRecord:
    ticket_id: str
    cohort_week: str
    human_replied_after_ai: bool | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ticket_id, str)
            or _TICKET_ID.fullmatch(self.ticket_id) is None
            or (
                self.human_replied_after_ai is not None
                and not isinstance(self.human_replied_after_ai, bool)
            )
        ):
            raise ReconciliationCacheError(
                "Outcome reconciliation cache record is invalid"
            )
        _validate_monday(self.cohort_week, "record cohort week")


@dataclass(frozen=True)
class ReconciliationCache:
    fetched_weeks: Mapping[str, str]
    records: tuple[ReconciliationRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.fetched_weeks, Mapping):
            raise ReconciliationCacheError(
                "Outcome reconciliation fetched weeks are invalid"
            )

        normalized_weeks: dict[str, str] = {}
        for week, fetched_at in self.fetched_weeks.items():
            _validate_monday(week, "fetched week")
            _validate_utc_timestamp(fetched_at)
            normalized_weeks[week] = fetched_at

        try:
            source_records = tuple(self.records)
        except TypeError:
            raise ReconciliationCacheError(
                "Outcome reconciliation cache records are invalid"
            ) from None
        if any(not isinstance(record, ReconciliationRecord) for record in source_records):
            raise ReconciliationCacheError(
                "Outcome reconciliation cache records are invalid"
            )

        normalized_records = tuple(
            ReconciliationRecord(
                ticket_id=record.ticket_id,
                cohort_week=record.cohort_week,
                human_replied_after_ai=record.human_replied_after_ai,
            )
            for record in source_records
        )
        ticket_ids = [record.ticket_id for record in normalized_records]
        if len(ticket_ids) != len(set(ticket_ids)):
            raise ReconciliationCacheError(
                "Outcome reconciliation cache contains duplicate tickets"
            )

        object.__setattr__(
            self,
            "fetched_weeks",
            MappingProxyType(dict(sorted(normalized_weeks.items()))),
        )
        object.__setattr__(self, "records", normalized_records)

    @property
    def fetched_at(self) -> str | None:
        return max(self.fetched_weeks.values(), default=None)


def load_reconciliation_cache(path: Path) -> ReconciliationCache | None:
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise ReconciliationCacheError(
            "Outcome reconciliation cache is invalid"
        ) from None

    if not _is_private_owner_file(source_status):
        raise ReconciliationCacheError("Outcome reconciliation cache is invalid")

    descriptor: int | None = None
    try:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        opened_status = os.fstat(descriptor)
        if (
            not _is_private_owner_file(opened_status)
            or source_status.st_dev != opened_status.st_dev
            or source_status.st_ino != opened_status.st_ino
        ):
            raise ReconciliationCacheError(
                "Outcome reconciliation cache is invalid"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            value = json.load(stream, object_pairs_hook=_strict_json_object)
    except ReconciliationCacheError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJSONKey):
        raise ReconciliationCacheError(
            "Outcome reconciliation cache is invalid"
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)

    return _cache_from_value(value)


def write_reconciliation_cache(path: Path, cache: ReconciliationCache) -> None:
    payload = _cache_to_value(cache)
    _atomic_private_json(Path(path), payload)


def _cache_from_value(value: object) -> ReconciliationCache:
    if not isinstance(value, Mapping) or set(value) != _CACHE_KEYS:
        raise ReconciliationCacheError("Outcome reconciliation cache is invalid")
    if (
        not isinstance(value["schema_version"], int)
        or isinstance(value["schema_version"], bool)
        or value["schema_version"] != _CACHE_SCHEMA_VERSION
    ):
        raise ReconciliationCacheError(
            "Outcome reconciliation cache version is invalid"
        )

    raw_weeks = value["fetched_weeks"]
    raw_records = value["records"]
    if not isinstance(raw_weeks, Mapping) or not isinstance(raw_records, list):
        raise ReconciliationCacheError("Outcome reconciliation cache is invalid")

    records: list[ReconciliationRecord] = []
    for item in raw_records:
        if not isinstance(item, Mapping) or set(item) != _RECORD_KEYS:
            raise ReconciliationCacheError(
                "Outcome reconciliation cache record is invalid"
            )
        records.append(
            ReconciliationRecord(
                ticket_id=item["ticket_id"],
                cohort_week=item["cohort_week"],
                human_replied_after_ai=item["human_replied_after_ai"],
            )
        )

    return ReconciliationCache(
        fetched_weeks=dict(raw_weeks),
        records=tuple(records),
    )


def _cache_to_value(cache: ReconciliationCache) -> dict[str, object]:
    if not isinstance(cache, ReconciliationCache):
        raise ReconciliationCacheError("Outcome reconciliation cache is invalid")
    validated = ReconciliationCache(
        fetched_weeks=cache.fetched_weeks,
        records=cache.records,
    )
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "fetched_weeks": dict(validated.fetched_weeks),
        "records": [
            {
                "ticket_id": record.ticket_id,
                "cohort_week": record.cohort_week,
                "human_replied_after_ai": record.human_replied_after_ai,
            }
            for record in validated.records
        ],
    }


def _validate_monday(value: object, label: str) -> None:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise ReconciliationCacheError(
            f"Outcome reconciliation {label} is invalid"
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ReconciliationCacheError(
            f"Outcome reconciliation {label} is invalid"
        ) from None
    if parsed.isoformat() != value or parsed.weekday() != 0:
        raise ReconciliationCacheError(
            f"Outcome reconciliation {label} is invalid"
        )


def _validate_utc_timestamp(value: object) -> None:
    if not isinstance(value, str):
        raise ReconciliationCacheError(
            "Outcome reconciliation fetched timestamp is invalid"
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ReconciliationCacheError(
            "Outcome reconciliation fetched timestamp is invalid"
        ) from None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timedelta(0)
    ):
        raise ReconciliationCacheError(
            "Outcome reconciliation fetched timestamp is invalid"
        )


def _is_private_owner_file(details: os.stat_result) -> bool:
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_uid == os.geteuid()
        and stat.S_IMODE(details.st_mode) == 0o600
    )


def _is_private_owner_directory(details: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(details.st_mode)
        and details.st_uid == os.geteuid()
        and stat.S_IMODE(details.st_mode) == 0o700
    )


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJSONKey
        value[key] = item
    return value


def _atomic_private_json(path: Path, payload: object) -> None:
    parent = path.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(parent, 0o700)
    except FileExistsError:
        try:
            parent_status = parent.lstat()
        except OSError:
            raise ReconciliationCacheError(
                "Outcome reconciliation cache could not be written"
            ) from None
        if not _is_private_owner_directory(parent_status):
            raise ReconciliationCacheError(
                "Outcome reconciliation cache could not be written"
            )
    except OSError:
        raise ReconciliationCacheError(
            "Outcome reconciliation cache could not be written"
        ) from None

    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=parent,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError:
        raise ReconciliationCacheError(
            "Outcome reconciliation cache could not be written"
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
