from __future__ import annotations

"""Freshdesk inventory join and privacy-safe entry-coverage classification."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Literal

from .dashboard_schema import TicketRow
from .entry_coverage_cache import EntryCoverageRecord
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
]


class FreshdeskEntryCoverageError(RuntimeError):
    """A sanitized Freshdesk entry-coverage contract error."""


_RAW_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


@dataclass(frozen=True)
class FreshdeskTicketMetadata:
    ticket_id: str
    created_at: str
    # The 5 fields below are the raw, unvalidated-against-any-allowlist AI
    # post-review custom fields. Kept permissive here (shape only) because
    # every caller of this struct -- CSAT, entry coverage, reconciliation --
    # constructs it regardless of whether it cares about AI review, and a new
    # CS-added dropdown option must not break jobs that never look at these
    # fields. Allowlist/fail-closed parsing lives in ai_review.py instead.
    ai_review_rating_raw: str | None = None
    ai_review_count_raw: str | None = None
    ai_review_date_raw: str | None = None
    ai_reopen_status_raw: str | None = None
    ai_user_replied_raw: str | None = None

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
        if (
            (self.ai_review_rating_raw is not None and not self.ai_review_rating_raw)
            or (self.ai_review_count_raw is not None and not self.ai_review_count_raw)
            or (self.ai_reopen_status_raw is not None and not self.ai_reopen_status_raw)
            or (self.ai_user_replied_raw is not None and not self.ai_user_replied_raw)
            or (
                self.ai_review_date_raw is not None
                and _RAW_ISO_DATE.fullmatch(self.ai_review_date_raw) is None
            )
        ):
            raise FreshdeskEntryCoverageError("Freshdesk ticket metadata is invalid")


def classify_entry_coverage(
    ticket: FreshdeskTicketMetadata,
    langfuse_ticket: TicketRow,
    conversations: tuple[ConversationMetadata, ...],
    agents: ReconciliationAgentConfig,
) -> EntryCoverageRecord:
    """Classify one Freshdesk ticket already known to Langfuse."""

    if not isinstance(ticket, FreshdeskTicketMetadata):
        raise FreshdeskEntryCoverageError("Freshdesk ticket metadata is invalid")
    if not isinstance(langfuse_ticket, TicketRow):
        raise FreshdeskEntryCoverageError("Langfuse ticket is invalid")
    if not isinstance(conversations, tuple) or any(
        not isinstance(row, ConversationMetadata) for row in conversations
    ):
        raise FreshdeskEntryCoverageError("Freshdesk conversation metadata is invalid")

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

    return EntryCoverageRecord(
        ticket_id=ticket.ticket_id,
        opened_at=ticket.created_at,
        cohort_week=_cohort_week(ticket.created_at),
        status=status,
        human_replied=human_replied,
    )


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
