from __future__ import annotations

"""Private, resumable state for the Freshdesk entry-coverage job.

The checkpoint contains only the projected Freshdesk metadata and derived
entry-coverage fields.  It is never loaded by the serving process.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .entry_coverage_cache import ENTRY_COVERAGE_START_WEEK, EntryCoverageRecord
from .freshdesk_entry_coverage import FreshdeskTicketMetadata


CHECKPOINT_SCHEMA_VERSION = 1
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class EntryCoverageCheckpointError(RuntimeError):
    """A sanitized private-checkpoint contract error."""


class _DuplicateJSONKey(ValueError):
    pass


@dataclass(frozen=True)
class InventoryCheckpoint:
    source_start_week: str
    updated_since: str
    page_size: int
    next_page: int
    complete: bool
    tickets: tuple[FreshdeskTicketMetadata, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        _validate_start_week(self.source_start_week)
        _validate_utc(self.updated_since)
        if self.page_size != 50 or self.next_page < 1 or not isinstance(self.complete, bool):
            raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint is invalid")
        if not _FINGERPRINT.fullmatch(self.fingerprint):
            raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint is invalid")
        tickets = tuple(self.tickets)
        if any(not isinstance(item, FreshdeskTicketMetadata) for item in tickets):
            raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint is invalid")
        ids = tuple(item.ticket_id for item in tickets)
        if len(ids) != len(set(ids)):
            raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint has duplicate tickets")
        object.__setattr__(self, "tickets", tickets)


@dataclass(frozen=True)
class CoverageCheckpoint:
    source_start_week: str
    inventory_fingerprint: str
    target_weeks: tuple[str, ...]
    active_week: str | None
    next_ticket_index: int
    completed_weeks: tuple[str, ...]
    records: tuple[EntryCoverageRecord, ...]

    def __post_init__(self) -> None:
        _validate_start_week(self.source_start_week)
        if not _FINGERPRINT.fullmatch(self.inventory_fingerprint):
            raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
        target_weeks = _normalize_weeks(self.target_weeks)
        completed_weeks = _normalize_weeks(self.completed_weeks)
        if not set(completed_weeks).issubset(target_weeks):
            raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
        if self.active_week is not None and self.active_week not in target_weeks:
            raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
        if self.next_ticket_index < 0:
            raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
        records = tuple(self.records)
        if any(not isinstance(item, EntryCoverageRecord) for item in records):
            raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
        if len({item.ticket_id for item in records}) != len(records):
            raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint has duplicate tickets")
        object.__setattr__(self, "target_weeks", target_weeks)
        object.__setattr__(self, "completed_weeks", completed_weeks)
        object.__setattr__(self, "records", records)


def inventory_fingerprint(tickets: tuple[FreshdeskTicketMetadata, ...]) -> str:
    """Hash only the stable projected inventory fields."""

    canonical = json.dumps(
        [[item.ticket_id, item.created_at] for item in tickets],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def load_inventory_checkpoint(path: Path) -> InventoryCheckpoint | None:
    value = _load_private_json(Path(path))
    if value is None:
        return None
    if set(value) != {
        "schema_version",
        "source_start_week",
        "updated_since",
        "page_size",
        "next_page",
        "complete",
        "tickets",
        "fingerprint",
    }:
        raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint is invalid")
    if value["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
        raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint version is invalid")
    raw_tickets = value["tickets"]
    if not isinstance(raw_tickets, list):
        raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint is invalid")
    tickets = tuple(
        FreshdeskTicketMetadata(
            ticket_id=item["ticket_id"],
            created_at=item["created_at"],
        )
        for item in raw_tickets
        if isinstance(item, Mapping)
        and set(item) == {"ticket_id", "created_at"}
    )
    if len(tickets) != len(raw_tickets):
        raise EntryCoverageCheckpointError("Freshdesk inventory checkpoint is invalid")
    return InventoryCheckpoint(
        source_start_week=value["source_start_week"],
        updated_since=value["updated_since"],
        page_size=value["page_size"],
        next_page=value["next_page"],
        complete=value["complete"],
        tickets=tickets,
        fingerprint=value["fingerprint"],
    )


def write_inventory_checkpoint(path: Path, checkpoint: InventoryCheckpoint) -> None:
    _write_private_json(Path(path), _inventory_value(checkpoint))


def load_coverage_checkpoint(path: Path) -> CoverageCheckpoint | None:
    value = _load_private_json(Path(path))
    if value is None:
        return None
    expected = {
        "schema_version",
        "source_start_week",
        "inventory_fingerprint",
        "target_weeks",
        "active_week",
        "next_ticket_index",
        "completed_weeks",
        "records",
    }
    if set(value) != expected:
        raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
    if value["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
        raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint version is invalid")
    raw_weeks = value["target_weeks"]
    raw_completed = value["completed_weeks"]
    raw_records = value["records"]
    if (
        not isinstance(raw_weeks, list)
        or not isinstance(raw_completed, list)
        or not isinstance(raw_records, list)
    ):
        raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
    records = tuple(
        EntryCoverageRecord(
            ticket_id=item["ticket_id"],
            opened_at=item["opened_at"],
            cohort_week=item["cohort_week"],
            status=item["status"],
            human_replied=item["human_replied"],
        )
        for item in raw_records
        if isinstance(item, Mapping)
        and set(item)
        == {"ticket_id", "opened_at", "cohort_week", "status", "human_replied"}
    )
    if len(records) != len(raw_records):
        raise EntryCoverageCheckpointError("Freshdesk coverage checkpoint is invalid")
    return CoverageCheckpoint(
        source_start_week=value["source_start_week"],
        inventory_fingerprint=value["inventory_fingerprint"],
        target_weeks=tuple(raw_weeks),
        active_week=value["active_week"],
        next_ticket_index=value["next_ticket_index"],
        completed_weeks=tuple(raw_completed),
        records=records,
    )


def write_coverage_checkpoint(path: Path, checkpoint: CoverageCheckpoint) -> None:
    _write_private_json(Path(path), _coverage_value(checkpoint))


def _inventory_value(checkpoint: InventoryCheckpoint) -> dict[str, object]:
    validated = checkpoint
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "source_start_week": validated.source_start_week,
        "updated_since": validated.updated_since,
        "page_size": validated.page_size,
        "next_page": validated.next_page,
        "complete": validated.complete,
        "tickets": [
            {"ticket_id": item.ticket_id, "created_at": item.created_at}
            for item in validated.tickets
        ],
        "fingerprint": validated.fingerprint,
    }


def _coverage_value(checkpoint: CoverageCheckpoint) -> dict[str, object]:
    validated = checkpoint
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "source_start_week": validated.source_start_week,
        "inventory_fingerprint": validated.inventory_fingerprint,
        "target_weeks": list(validated.target_weeks),
        "active_week": validated.active_week,
        "next_ticket_index": validated.next_ticket_index,
        "completed_weeks": list(validated.completed_weeks),
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


def _load_private_json(path: Path) -> dict[str, object] | None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise EntryCoverageCheckpointError("Freshdesk checkpoint is invalid") from None
    if not _is_private_file(details):
        raise EntryCoverageCheckpointError("Freshdesk checkpoint is invalid")
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not _is_private_file(opened)
            or opened.st_dev != details.st_dev
            or opened.st_ino != details.st_ino
        ):
            raise EntryCoverageCheckpointError("Freshdesk checkpoint is invalid")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            value = json.load(stream, object_pairs_hook=_strict_object)
    except EntryCoverageCheckpointError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateJSONKey):
        raise EntryCoverageCheckpointError("Freshdesk checkpoint is invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise EntryCoverageCheckpointError("Freshdesk checkpoint is invalid")
    return value


def _write_private_json(path: Path, value: object) -> None:
    directory = path.parent
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        if not directory.exists():
            directory.mkdir(mode=0o700, parents=True)
        if not stat.S_ISDIR(directory.stat().st_mode):
            raise EntryCoverageCheckpointError("Freshdesk checkpoint directory is invalid")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=directory
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except EntryCoverageCheckpointError:
        raise
    except OSError:
        raise EntryCoverageCheckpointError("Freshdesk checkpoint could not be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _is_private_file(details: os.stat_result) -> bool:
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_uid == os.geteuid()
        and stat.S_IMODE(details.st_mode) == 0o600
    )


def _validate_start_week(value: object) -> None:
    if value != ENTRY_COVERAGE_START_WEEK:
        raise EntryCoverageCheckpointError("Freshdesk checkpoint start week is invalid")


def _validate_utc(value: object) -> None:
    if not isinstance(value, str):
        raise EntryCoverageCheckpointError("Freshdesk checkpoint timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise EntryCoverageCheckpointError("Freshdesk checkpoint timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise EntryCoverageCheckpointError("Freshdesk checkpoint timestamp is invalid")


def _normalize_weeks(values: tuple[str, ...] | list[object]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
            raise EntryCoverageCheckpointError("Freshdesk checkpoint week is invalid")
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise EntryCoverageCheckpointError("Freshdesk checkpoint week is invalid") from None
        if parsed.isoformat() != value or parsed.weekday() != 0 or value < ENTRY_COVERAGE_START_WEEK:
            raise EntryCoverageCheckpointError("Freshdesk checkpoint week is invalid")
        normalized.append(value)
    if len(normalized) != len(set(normalized)):
        raise EntryCoverageCheckpointError("Freshdesk checkpoint weeks are invalid")
    return tuple(sorted(normalized))
