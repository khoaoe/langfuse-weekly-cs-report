from __future__ import annotations
from .cache_store import (
    atomic_private_json,
    read_private_json,
    validate_monday,
    validate_utc_timestamp,
)

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
        validate_monday(self.cohort_week, "record cohort week", ReconciliationCacheError)


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
            validate_monday(week, "fetched week", ReconciliationCacheError)
            validate_utc_timestamp(
                    fetched_at,
                    "fetched timestamp",
                    ReconciliationCacheError,
                    require_z_suffix=False,
                )
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
    value = read_private_json(Path(path), ReconciliationCacheError, "Freshdesk reconciliation cache is invalid")
    if value is None:
        return None
    return _cache_from_value(value)


def write_reconciliation_cache(path: Path, cache: ReconciliationCache) -> None:
    payload = _cache_to_value(cache)
    atomic_private_json(
        Path(path),
        payload,
        ReconciliationCacheError,
        "Freshdesk reconciliation cache could not be written",
    )


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

