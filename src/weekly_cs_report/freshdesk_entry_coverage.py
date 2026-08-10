from __future__ import annotations

"""Freshdesk inventory join and privacy-safe entry-coverage classification."""

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
import time
from typing import Literal

from .dashboard_schema import TicketRow
from .entry_coverage_cache import EntryCoverageCache, EntryCoverageRecord
from .outcome_reconciliation import (
    ConversationMetadata,
    ReconciliationAgentConfig,
    is_public_agent_reply,
)


_TICKET_ID = re.compile(r"[1-9][0-9]*\Z")
_UTC_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")

EntryCoverageStatus = Literal[
    "ai_replied_only",
    "ai_replied_then_transferred",
    "transferred_without_ai_reply",
    "invoked_no_result",
    "not_observed_invoked",
    "unresolved",
]


class FreshdeskEntryCoverageError(RuntimeError):
    """A sanitized Freshdesk entry-coverage contract error."""


class _FetchDurationReached(RuntimeError):
    pass


@dataclass(frozen=True)
class IncrementalEntryCoverageResult:
    cache: EntryCoverageCache
    completed_weeks: tuple[str, ...]
    complete: bool


@dataclass(frozen=True)
class FreshdeskTicketMetadata:
    ticket_id: str
    created_at: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.ticket_id, str)
            or _TICKET_ID.fullmatch(self.ticket_id) is None
            or not isinstance(self.created_at, str)
            or _UTC_ISO.fullmatch(self.created_at) is None
        ):
            raise FreshdeskEntryCoverageError("Freshdesk ticket metadata is invalid")
        try:
            parsed = datetime.fromisoformat(self.created_at[:-1] + "+00:00")
        except ValueError:
            raise FreshdeskEntryCoverageError("Freshdesk ticket metadata is invalid") from None
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise FreshdeskEntryCoverageError("Freshdesk ticket metadata is invalid")


def classify_entry_coverage(
    ticket: FreshdeskTicketMetadata,
    langfuse_ticket: TicketRow | None,
    conversations: tuple[ConversationMetadata, ...],
    agents: ReconciliationAgentConfig,
):
    """Classify one Freshdesk ticket without treating absence as causality."""

    if not isinstance(ticket, FreshdeskTicketMetadata):
        raise FreshdeskEntryCoverageError("Freshdesk ticket metadata is invalid")
    if not isinstance(conversations, tuple) or any(
        not isinstance(row, ConversationMetadata) for row in conversations
    ):
        raise FreshdeskEntryCoverageError("Freshdesk conversation metadata is invalid")

    if langfuse_ticket is not None:
        if langfuse_ticket.ai_first and not langfuse_ticket.transferred:
            status: EntryCoverageStatus = "ai_replied_only"
            human_replied = None
        elif langfuse_ticket.ai_first and langfuse_ticket.transferred:
            status = "ai_replied_then_transferred"
            human_replied = None
        elif langfuse_ticket.transferred:
            status = "transferred_without_ai_reply"
            human_replied = None
        else:
            status = "invoked_no_result"
            human_replied = _human_reply_state(conversations, agents)
    else:
        has_bot = False
        has_unknown = False
        has_human = False
        for row in conversations:
            if not is_public_agent_reply(row):
                continue
            if row.author_id in agents.bot_agent_ids:
                has_bot = True
            elif row.author_id in agents.human_agent_ids:
                has_human = True
            elif row.author_id in agents.excluded_agent_ids:
                continue
            else:
                has_unknown = True
        if has_bot or has_unknown:
            status = "unresolved"
            human_replied = None
        else:
            status = "not_observed_invoked"
            human_replied = has_human

    return EntryCoverageRecord(
        ticket_id=ticket.ticket_id,
        opened_at=ticket.created_at,
        cohort_week=_cohort_week(ticket.created_at),
        status=status,
        human_replied=human_replied,
    )


def fetch_entry_coverage_population(
    client: object,
    freshdesk_tickets: Sequence[FreshdeskTicketMetadata],
    langfuse_tickets: Mapping[str, TicketRow],
    target_weeks: Sequence[str],
    agents: ReconciliationAgentConfig,
    *,
    existing: EntryCoverageCache | None,
    as_of: datetime,
    max_workers: int = 1,
    max_duration_seconds: float = 30 * 60,
    on_week_complete: Callable[[EntryCoverageCache], None] | None = None,
    resume_records: Sequence[EntryCoverageRecord] = (),
    resume_week: str | None = None,
    resume_index: int = 0,
    on_progress: Callable[[EntryCoverageCache, str, int], None] | None = None,
) -> IncrementalEntryCoverageResult:
    """Fetch selected Freshdesk weeks atomically, preserving old cache weeks."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise FreshdeskEntryCoverageError("Entry coverage as-of is invalid")
    if max_workers < 1 or max_workers > 8 or max_duration_seconds <= 0:
        raise FreshdeskEntryCoverageError("Entry coverage options are invalid")
    normalized_weeks = _normalize_weeks(target_weeks)
    if any(
        not isinstance(item, FreshdeskTicketMetadata) for item in freshdesk_tickets
    ):
        raise FreshdeskEntryCoverageError("Freshdesk ticket metadata is invalid")
    grouped: dict[str, tuple[FreshdeskTicketMetadata, ...]] = {
        week: tuple(
            sorted(
                (
                    item
                    for item in freshdesk_tickets
                    if _cohort_week(item.created_at) == week
                ),
                key=lambda item: int(item.ticket_id),
            )
        )
        for week in normalized_weeks
    }
    if resume_index < 0 or (resume_index > 0 and resume_week is None):
        raise FreshdeskEntryCoverageError("Entry coverage resume cursor is invalid")
    if resume_week is not None and resume_week not in normalized_weeks:
        raise FreshdeskEntryCoverageError("Entry coverage resume week is invalid")
    resume_by_ticket = {item.ticket_id: item for item in resume_records}
    if len(resume_by_ticket) != len(tuple(resume_records)):
        raise FreshdeskEntryCoverageError("Entry coverage resume records are invalid")
    base = existing or EntryCoverageCache(fetched_weeks={}, records=())
    records_by_ticket = {item.ticket_id: item for item in base.records}
    records_by_ticket.update(resume_by_ticket)
    fetched_weeks = dict(base.fetched_weeks)
    completed: list[str] = []
    started = time.monotonic()
    for week in normalized_weeks:
        if not _week_needs_fetch(week, fetched_weeks, as_of.date()):
            continue
        if time.monotonic() - started >= max_duration_seconds:
            return _incremental_result(fetched_weeks, records_by_ticket, completed, False)
        start_index = resume_index if week == resume_week else 0
        try:
            week_records, week_complete, next_index = _fetch_week(
                client,
                week,
                grouped[week],
                langfuse_tickets,
                agents,
                max_workers=max_workers,
                should_stop=lambda: time.monotonic() - started >= max_duration_seconds,
                start_index=start_index,
                resume_records=resume_by_ticket,
                on_record=(
                    lambda record, index, current_week=week: _on_record_progress(
                        record,
                        index,
                        current_week,
                        records_by_ticket,
                        fetched_weeks,
                        on_progress,
                    )
                ),
            )
        except _FetchDurationReached:
            return _incremental_result(fetched_weeks, records_by_ticket, completed, False)
        records_by_ticket = {
            ticket_id: record
            for ticket_id, record in records_by_ticket.items()
            if record.cohort_week != week
        }
        records_by_ticket.update({item.ticket_id: item for item in week_records})
        if not week_complete:
            if on_progress is not None:
                on_progress(
                    _build_cache(fetched_weeks, records_by_ticket),
                    week,
                    next_index,
                )
            return _incremental_result(fetched_weeks, records_by_ticket, completed, False)
        fetched_weeks[week] = _utc_iso(as_of)
        completed.append(week)
        current = _build_cache(fetched_weeks, records_by_ticket)
        if on_week_complete is not None:
            on_week_complete(current)
    return _incremental_result(fetched_weeks, records_by_ticket, completed, True)


def _fetch_week(
    client: object,
    week: str,
    tickets: Sequence[FreshdeskTicketMetadata],
    langfuse_tickets: Mapping[str, TicketRow],
    agents: ReconciliationAgentConfig,
    *,
    max_workers: int,
    should_stop: Callable[[], bool],
    start_index: int = 0,
    resume_records: Mapping[str, EntryCoverageRecord] | None = None,
    on_record: Callable[[EntryCoverageRecord, int], None] | None = None,
) -> tuple[tuple[EntryCoverageRecord, ...], bool, int]:
    fetch = getattr(client, "get_conversation_metadata", None)
    if not callable(fetch):
        raise FreshdeskEntryCoverageError("Freshdesk conversation client is invalid")

    def classify(item: FreshdeskTicketMetadata) -> EntryCoverageRecord:
        if should_stop():
            raise _FetchDurationReached
        langfuse_ticket = langfuse_tickets.get(item.ticket_id)
        needs_conversations = langfuse_ticket is None or (
            not langfuse_ticket.ai_first and not langfuse_ticket.transferred
        )
        conversations: tuple[ConversationMetadata, ...] = ()
        if needs_conversations:
            value = fetch(item.ticket_id, should_stop=should_stop)
            if not isinstance(value, tuple) or any(
                not isinstance(row, ConversationMetadata) for row in value
            ):
                raise FreshdeskEntryCoverageError(
                    "Freshdesk conversation metadata is invalid"
                )
            conversations = value
        result = classify_entry_coverage(item, langfuse_ticket, conversations, agents)
        if result.cohort_week != week:
            raise FreshdeskEntryCoverageError("Freshdesk ticket cohort is invalid")
        return result

    if max_workers != 1:
        # Resume cursors and progress checkpoints are deliberately serial. The
        # CLI defaults to one worker because Freshdesk is rate-limited, while
        # preserving the old parallel API for callers that do not resume.
        if start_index or resume_records or on_record is not None:
            raise FreshdeskEntryCoverageError("Entry coverage resume requires one worker")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = tuple(executor.submit(classify, item) for item in tickets)
            return tuple(future.result() for future in futures), True, len(tickets)
    records: list[EntryCoverageRecord] = []
    resume_records = resume_records or {}
    for index, item in enumerate(tickets):
        if index < start_index:
            resumed = resume_records.get(item.ticket_id)
            if resumed is None or resumed.opened_at != item.created_at:
                raise FreshdeskEntryCoverageError("Entry coverage resume cursor is invalid")
            records.append(resumed)
            continue
        try:
            result = classify(item)
        except _FetchDurationReached:
            return tuple(records), False, index
        records.append(result)
        if on_record is not None:
            on_record(result, index + 1)
    return tuple(records), True, len(tickets)


def _on_record_progress(
    record: EntryCoverageRecord,
    index: int,
    week: str,
    records_by_ticket: dict[str, EntryCoverageRecord],
    fetched_weeks: Mapping[str, str],
    callback: Callable[[EntryCoverageCache, str, int], None] | None,
) -> None:
    records_by_ticket[record.ticket_id] = record
    if callback is not None:
        callback(_build_cache(fetched_weeks, records_by_ticket), week, index)


def _normalize_weeks(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise FreshdeskEntryCoverageError("Entry coverage week is invalid") from None
        if parsed.weekday() != 0 or parsed.isoformat() != value:
            raise FreshdeskEntryCoverageError("Entry coverage week is invalid")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise FreshdeskEntryCoverageError("Entry coverage weeks contain duplicates")
    return tuple(sorted(normalized))


def _week_needs_fetch(
    week: str,
    fetched_weeks: Mapping[str, str],
    current_date: date,
) -> bool:
    if week not in fetched_weeks:
        return True
    return current_date <= date.fromisoformat(week) + timedelta(days=20)


def _build_cache(
    fetched_weeks: Mapping[str, str],
    records_by_ticket: Mapping[str, EntryCoverageRecord],
) -> EntryCoverageCache:
    return EntryCoverageCache(
        fetched_weeks=fetched_weeks,
        records=tuple(
            sorted(
                records_by_ticket.values(),
                key=lambda item: (item.cohort_week, int(item.ticket_id)),
            )
        ),
    )


def _incremental_result(
    fetched_weeks: Mapping[str, str],
    records_by_ticket: Mapping[str, EntryCoverageRecord],
    completed: Sequence[str],
    complete: bool,
) -> IncrementalEntryCoverageResult:
    return IncrementalEntryCoverageResult(
        cache=_build_cache(fetched_weeks, records_by_ticket),
        completed_weeks=tuple(completed),
        complete=complete,
    )


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _human_reply_state(
    conversations: tuple[ConversationMetadata, ...],
    agents: ReconciliationAgentConfig,
) -> bool | None:
    unknown = False
    for row in conversations:
        if not is_public_agent_reply(row):
            continue
        if row.author_id in agents.human_agent_ids:
            return True
        if (
            row.author_id not in agents.bot_agent_ids
            and row.author_id not in agents.excluded_agent_ids
        ):
            unknown = True
    return None if unknown else False


def _cohort_week(created_at: str) -> str:
    from .cohort import VIETNAM_TIMEZONE, cohort_week_for

    parsed = datetime.fromisoformat(created_at[:-1] + "+00:00")
    return cohort_week_for(parsed.astimezone(VIETNAM_TIMEZONE)).isoformat()
