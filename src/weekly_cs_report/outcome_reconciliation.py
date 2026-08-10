from __future__ import annotations

"""Privacy-safe identity and sequence rules for Freshdesk reconciliation.

Conversation metadata exists only in memory.  The persisted reconciliation
cache is deliberately implemented in a separate module whose record contains
only the final tri-state result for one ticket.
"""

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from unicodedata import combining, normalize

from .reconciliation_cache import (
    ReconciliationCache,
    ReconciliationRecord,
)


_CONFIG_KEYS = {
    "schema_version",
    "approved_by",
    "approved_at",
    "bot_agent_ids",
    "human_agent_ids",
    "excluded_agent_ids",
    "source_hash",
}
_SOURCE_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TICKET_ID = re.compile(r"[1-9][0-9]*\Z")
_CANDIDATE_ARTIFACT_KEYS = {
    "schema_version",
    "generated_at",
    "source",
    "status",
    "approved_by",
    "approved_at",
    "approved_bot_excluded",
    "instructions",
    "candidates",
}
_CANDIDATE_KEYS = {"agent_id", "display_name", "decision"}
_SERVICE_NAME_TOKENS = frozenset(
    {
        "admin",
        "agent",
        "automation",
        "bot",
        "call",
        "callcenter",
        "center",
        "cs",
        "cskh",
        "demo",
        "hotro",
        "operator",
        "ops",
        "qa",
        "robot",
        "service",
        "support",
        "system",
        "team",
        "test",
        "thongtin",
        "vanhanh",
        "zalopay",
    }
)
_SERVICE_NAME_PHRASES = ("he thong", "ho tro", "thong tin", "van hanh")


class OutcomeReconciliationError(RuntimeError):
    """Sanitized reconciliation failure safe for the CLI boundary."""


class _FetchDurationReached(RuntimeError):
    pass


@dataclass(frozen=True)
class ConversationMetadata:
    """Transient allowlist projected immediately from one conversation."""

    conversation_id: int
    author_id: int | None
    incoming: bool
    private: bool
    source: int
    created_at: str
    category: int | None = None
    is_autorep_private_note: bool = False

    def __post_init__(self) -> None:
        if (
            not _positive_int(self.conversation_id)
            or (self.author_id is not None and not _positive_int(self.author_id))
            or not isinstance(self.incoming, bool)
            or not isinstance(self.private, bool)
            or not isinstance(self.source, int)
            or isinstance(self.source, bool)
            or self.source < 0
            or (
                self.category is not None
                and (
                    not isinstance(self.category, int)
                    or isinstance(self.category, bool)
                    or self.category < 0
                )
            )
            or not isinstance(self.is_autorep_private_note, bool)
        ):
            raise OutcomeReconciliationError(
                "Freshdesk conversation metadata is invalid"
            )
        _parse_utc(self.created_at)


@dataclass(frozen=True)
class ReconciliationAgentConfig:
    approved_by: str
    approved_at: str
    bot_agent_ids: frozenset[int]
    human_agent_ids: frozenset[int]
    excluded_agent_ids: frozenset[int]
    source_hash: str

    def __post_init__(self) -> None:
        groups = (
            self.bot_agent_ids,
            self.human_agent_ids,
            self.excluded_agent_ids,
        )
        if (
            self.approved_by != "PO"
            or not isinstance(self.approved_at, str)
            or not isinstance(self.source_hash, str)
            or _SOURCE_HASH.fullmatch(self.source_hash) is None
            or not self.bot_agent_ids
            or not self.human_agent_ids
            or any(not _positive_int(value) for group in groups for value in group)
            or any(
                left & right
                for index, left in enumerate(groups)
                for right in groups[index + 1 :]
            )
        ):
            raise OutcomeReconciliationError(
                "Freshdesk reconciliation agent config is invalid"
            )
        try:
            date.fromisoformat(self.approved_at)
        except ValueError:
            raise OutcomeReconciliationError(
                "Freshdesk reconciliation agent config is invalid"
            ) from None


@dataclass(frozen=True)
class IncrementalReconciliationResult:
    cache: ReconciliationCache
    completed_weeks: tuple[str, ...]
    complete: bool


def load_reconciliation_agent_config(
    path: Path,
    *,
    source_path: Path,
) -> ReconciliationAgentConfig:
    """Load one PO-approved roster and bind it to its private review artifact."""

    config_path = Path(path)
    approved_source = Path(source_path)
    _require_private_regular_file(config_path)
    _require_private_regular_file(approved_source)
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
        source_bytes = approved_source.read_bytes()
    except (OSError, json.JSONDecodeError):
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        ) from None
    if not isinstance(value, dict) or set(value) != _CONFIG_KEYS:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        )
    if value["schema_version"] != 1:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        )
    config = ReconciliationAgentConfig(
        approved_by=value["approved_by"],
        approved_at=value["approved_at"],
        bot_agent_ids=_id_set(value["bot_agent_ids"]),
        human_agent_ids=_id_set(value["human_agent_ids"]),
        excluded_agent_ids=_id_set(value["excluded_agent_ids"]),
        source_hash=value["source_hash"],
    )
    actual_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    if config.source_hash != actual_hash:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        )
    return config


def write_reconciliation_agent_config(
    path: Path,
    *,
    approved_at: date,
    bot_agent_ids: frozenset[int],
    human_agent_ids: frozenset[int],
    excluded_agent_ids: frozenset[int],
    source_path: Path,
) -> None:
    source = Path(source_path)
    _require_private_regular_file(source)
    try:
        source_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config could not be written"
        ) from None
    config = ReconciliationAgentConfig(
        approved_by="PO",
        approved_at=approved_at.isoformat(),
        bot_agent_ids=frozenset(bot_agent_ids),
        human_agent_ids=frozenset(human_agent_ids),
        excluded_agent_ids=frozenset(excluded_agent_ids),
        source_hash=source_hash,
    )
    payload = {
        "schema_version": 1,
        "approved_by": config.approved_by,
        "approved_at": config.approved_at,
        "bot_agent_ids": sorted(config.bot_agent_ids),
        "human_agent_ids": sorted(config.human_agent_ids),
        "excluded_agent_ids": sorted(config.excluded_agent_ids),
        "source_hash": config.source_hash,
    }
    _atomic_private_json(Path(path), payload)


def approve_reconciliation_candidates(
    source_path: Path,
    destination_path: Path,
    *,
    bot_agent_ids: frozenset[int],
    approved_at: date,
) -> dict[str, int]:
    """Apply the PO-approved conservative identity rule to a private roster."""

    source = Path(source_path)
    _require_private_regular_file(source)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation candidate artifact is invalid"
        ) from None
    if (
        not isinstance(value, dict)
        or set(value) != _CANDIDATE_ARTIFACT_KEYS
        or value["schema_version"] != 1
        or value["approved_bot_excluded"] is not True
        or not isinstance(value["candidates"], list)
    ):
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation candidate artifact is invalid"
        )
    candidates: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    human_ids: set[int] = set()
    excluded_ids: set[int] = set()
    for raw_candidate in value["candidates"]:
        if (
            not isinstance(raw_candidate, dict)
            or set(raw_candidate) != _CANDIDATE_KEYS
            or not _positive_int(raw_candidate["agent_id"])
            or not isinstance(raw_candidate["display_name"], str)
            or not raw_candidate["display_name"].strip()
            or raw_candidate["decision"] not in {
                "unreviewed",
                "human",
                "exclude",
            }
        ):
            raise OutcomeReconciliationError(
                "Freshdesk reconciliation candidate artifact is invalid"
            )
        agent_id = raw_candidate["agent_id"]
        if agent_id in seen_ids or agent_id in bot_agent_ids:
            raise OutcomeReconciliationError(
                "Freshdesk reconciliation candidate artifact is invalid"
            )
        seen_ids.add(agent_id)
        decision = (
            "human"
            if _looks_like_natural_person(raw_candidate["display_name"])
            else "exclude"
        )
        (human_ids if decision == "human" else excluded_ids).add(agent_id)
        candidates.append(
            {
                "agent_id": agent_id,
                "display_name": raw_candidate["display_name"],
                "decision": decision,
            }
        )
    if not human_ids:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation candidate artifact is invalid"
        )
    approved = {
        **value,
        "status": "approved",
        "approved_by": "PO",
        "approved_at": approved_at.isoformat(),
        "candidates": candidates,
    }
    _atomic_private_json(source, approved)
    write_reconciliation_agent_config(
        destination_path,
        approved_at=approved_at,
        bot_agent_ids=bot_agent_ids,
        human_agent_ids=frozenset(human_ids),
        excluded_agent_ids=frozenset(excluded_ids),
        source_path=source,
    )
    return {
        "candidate_count": len(candidates),
        "human_agent_count": len(human_ids),
        "excluded_agent_count": len(excluded_ids),
    }


def _looks_like_natural_person(value: str) -> bool:
    normalized = normalize("NFKC", value).strip()
    words = normalized.split()
    if not 2 <= len(words) <= 6:
        return False
    if any(not word.replace("-", "").isalpha() for word in words):
        return False
    folded = "".join(
        character
        for character in normalize("NFKD", normalized).casefold()
        if not combining(character)
    )
    tokens = set(folded.replace("-", " ").split())
    return not bool(tokens & _SERVICE_NAME_TOKENS) and not any(
        phrase in folded for phrase in _SERVICE_NAME_PHRASES
    )


def classify_human_reply_after_ai(
    conversations: tuple[ConversationMetadata, ...],
    config: ReconciliationAgentConfig,
) -> bool | None:
    """Return true, false, or unresolved for a reply after the approved bot."""

    public_outgoing = sorted(
        (
            row
            for row in conversations
            if is_public_agent_reply(row)
        ),
        key=lambda row: (_parse_utc(row.created_at), row.conversation_id),
    )
    bot_index = next(
        (
            index
            for index, row in enumerate(public_outgoing)
            if row.author_id in config.bot_agent_ids
        ),
        None,
    )
    if bot_index is None:
        return None
    unresolved = False
    known_ids = (
        config.bot_agent_ids
        | config.human_agent_ids
        | config.excluded_agent_ids
    )
    for row in public_outgoing[bot_index + 1 :]:
        if row.author_id in config.human_agent_ids:
            return True
        if row.author_id is None or row.author_id not in known_ids:
            unresolved = True
    return None if unresolved else False


def is_public_agent_reply(row: ConversationMetadata) -> bool:
    """Use Freshdesk category 3 when available, with legacy fallback."""

    if row.incoming or row.private or row.source == 6:
        return False
    if row.category is not None:
        return row.category == 3
    return True


def fetch_reconciliation_population(
    client: object,
    population: Mapping[str, Sequence[str]],
    config: ReconciliationAgentConfig,
    *,
    existing: ReconciliationCache | None,
    as_of: datetime,
    max_workers: int = 2,
    max_duration_seconds: float = 30 * 60,
    monotonic: Callable[[], float] = time.monotonic,
    on_week_complete: Callable[[ReconciliationCache], None] | None = None,
) -> IncrementalReconciliationResult:
    """Fetch complete weeks atomically while retaining only tri-state results."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise OutcomeReconciliationError(
            "Outcome reconciliation as-of must include a timezone"
        )
    if max_workers < 1 or max_workers > 8 or max_duration_seconds <= 0:
        raise OutcomeReconciliationError(
            "Outcome reconciliation options are invalid"
        )
    normalized = _normalize_population(population)
    base = existing or ReconciliationCache(fetched_weeks={}, records=())
    target_weeks = tuple(
        week
        for week in sorted(normalized)
        if _week_needs_fetch(week, base.fetched_weeks, as_of.date())
    )
    started_at = monotonic()
    fetched_weeks = dict(base.fetched_weeks)
    records_by_ticket = {record.ticket_id: record for record in base.records}
    completed: list[str] = []
    for week in target_weeks:
        if monotonic() - started_at >= max_duration_seconds:
            return _incremental_result(
                fetched_weeks,
                records_by_ticket,
                completed,
                complete=False,
            )
        try:
            records = _fetch_reconciliation_week(
                client,
                week,
                normalized[week],
                config,
                max_workers=max_workers,
                should_stop=lambda: (
                    monotonic() - started_at >= max_duration_seconds
                ),
            )
        except _FetchDurationReached:
            return _incremental_result(
                fetched_weeks,
                records_by_ticket,
                completed,
                complete=False,
            )
        records_by_ticket = {
            ticket_id: record
            for ticket_id, record in records_by_ticket.items()
            if record.cohort_week != week
        }
        records_by_ticket.update(
            {record.ticket_id: record for record in records}
        )
        fetched_weeks[week] = _format_utc(as_of)
        completed.append(week)
        if on_week_complete is not None:
            on_week_complete(
                _build_reconciliation_cache(fetched_weeks, records_by_ticket)
            )
    return _incremental_result(
        fetched_weeks,
        records_by_ticket,
        completed,
        complete=True,
    )


def _fetch_reconciliation_week(
    client: object,
    cohort_week: str,
    ticket_ids: tuple[str, ...],
    config: ReconciliationAgentConfig,
    *,
    max_workers: int,
    should_stop: Callable[[], bool],
) -> tuple[ReconciliationRecord, ...]:
    fetch = getattr(client, "get_conversation_metadata", None)
    if not callable(fetch):
        raise OutcomeReconciliationError(
            "Freshdesk conversation client is invalid"
        )

    def classify(ticket_id: str) -> ReconciliationRecord:
        conversations = fetch(ticket_id)
        if not isinstance(conversations, tuple) or any(
            not isinstance(row, ConversationMetadata) for row in conversations
        ):
            raise OutcomeReconciliationError(
                "Freshdesk conversation metadata is invalid"
            )
        return ReconciliationRecord(
            ticket_id=ticket_id,
            cohort_week=cohort_week,
            human_replied_after_ai=classify_human_reply_after_ai(
                conversations,
                config,
            ),
        )

    records: list[ReconciliationRecord] = []
    if max_workers == 1:
        for ticket_id in ticket_ids:
            if should_stop():
                raise _FetchDurationReached
            records.append(classify(ticket_id))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for start in range(0, len(ticket_ids), max_workers):
                if should_stop():
                    raise _FetchDurationReached
                batch = ticket_ids[start : start + max_workers]
                futures = tuple(executor.submit(classify, item) for item in batch)
                records.extend(future.result() for future in futures)
    return tuple(records)


def _normalize_population(
    population: Mapping[str, Sequence[str]],
) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for raw_week, raw_ticket_ids in population.items():
        try:
            week = date.fromisoformat(raw_week)
        except (TypeError, ValueError):
            raise OutcomeReconciliationError(
                "Outcome reconciliation population week is invalid"
            ) from None
        if week.weekday() != 0:
            raise OutcomeReconciliationError(
                "Outcome reconciliation population week is invalid"
            )
        raw_ids = {str(item) for item in raw_ticket_ids}
        if any(_TICKET_ID.fullmatch(item) is None for item in raw_ids):
            raise OutcomeReconciliationError(
                "Outcome reconciliation population ticket is invalid"
            )
        ticket_ids = tuple(sorted(raw_ids, key=int))
        if seen.intersection(ticket_ids):
            raise OutcomeReconciliationError(
                "Outcome reconciliation population contains duplicate tickets"
            )
        seen.update(ticket_ids)
        normalized[week.isoformat()] = ticket_ids
    return dict(sorted(normalized.items()))


def _week_needs_fetch(
    week: str,
    fetched_weeks: Mapping[str, str],
    current_date: date,
) -> bool:
    if week not in fetched_weeks:
        return True
    week_end = date.fromisoformat(week) + timedelta(days=6)
    return current_date <= week_end + timedelta(days=14)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_reconciliation_cache(
    fetched_weeks: Mapping[str, str],
    records_by_ticket: Mapping[str, ReconciliationRecord],
) -> ReconciliationCache:
    return ReconciliationCache(
        fetched_weeks=fetched_weeks,
        records=tuple(
            sorted(
                records_by_ticket.values(),
                key=lambda record: (
                    record.cohort_week,
                    int(record.ticket_id),
                ),
            )
        ),
    )


def _incremental_result(
    fetched_weeks: Mapping[str, str],
    records_by_ticket: Mapping[str, ReconciliationRecord],
    completed: Sequence[str],
    *,
    complete: bool,
) -> IncrementalReconciliationResult:
    return IncrementalReconciliationResult(
        cache=_build_reconciliation_cache(fetched_weeks, records_by_ticket),
        completed_weeks=tuple(completed),
        complete=complete,
    )


def _id_set(value: object) -> frozenset[int]:
    if not isinstance(value, list):
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        )
    result = frozenset(value)
    if len(result) != len(value) or any(not _positive_int(item) for item in result):
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        )
    return result


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise OutcomeReconciliationError("Freshdesk conversation timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise OutcomeReconciliationError(
            "Freshdesk conversation timestamp is invalid"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OutcomeReconciliationError(
            "Freshdesk conversation timestamp is invalid"
        )
    return parsed.astimezone(timezone.utc)


def _require_private_regular_file(path: Path) -> None:
    try:
        status = path.lstat()
    except OSError:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        ) from None
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != os.geteuid()
        or stat.S_IMODE(status.st_mode) != 0o600
    ):
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config is invalid"
        )


def _atomic_private_json(path: Path, payload: object) -> None:
    directory = path.parent
    try:
        if not directory.exists():
            directory.mkdir(mode=0o700, parents=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=directory
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError:
        raise OutcomeReconciliationError(
            "Freshdesk reconciliation agent config could not be written"
        ) from None
