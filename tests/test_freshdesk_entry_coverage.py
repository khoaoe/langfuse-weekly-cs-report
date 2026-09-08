from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json

import httpx
import pytest

from weekly_cs_report.dashboard_schema import TicketRow
from weekly_cs_report.freshdesk_csat import (
    FreshdeskCSATError,
    FreshdeskClient,
    FreshdeskSettings,
)
from weekly_cs_report.freshdesk_entry_coverage import (
    EntryCoverageStatus,
    FreshdeskEntryCoverageError,
    FreshdeskTicketMetadata,
    classify_entry_coverage,
)
from weekly_cs_report.outcome_reconciliation import (
    ConversationMetadata,
    ReconciliationAgentConfig,
)


BOT = 10_001
HUMAN = 10_002
EXCLUDED = 10_003
UNKNOWN = 10_004


def _config() -> ReconciliationAgentConfig:
    return ReconciliationAgentConfig(
        approved_by="PO",
        approved_at="2026-08-03",
        bot_agent_ids=frozenset({BOT}),
        human_agent_ids=frozenset({HUMAN}),
        excluded_agent_ids=frozenset({EXCLUDED}),
        source_hash="sha256:" + "1" * 64,
    )


def _ticket(*, ai_first: bool, transferred: bool) -> TicketRow:
    return TicketRow(
        ticket_id="123",
        opened_at="2026-08-03T01:00:00Z",
        cohort_week="2026-08-03",
        cohort_status="wtd",
        is_weekend_start=False,
        outcome="ai_end_to_end" if ai_first and not transferred else "direct_cs",
        ai_first=ai_first,
        transferred=transferred,
        reopen_lifetime=0,
        reopen_within_7d=0,
        ai_reply_count=1 if ai_first else 0,
        turn_count=1,
        gt4_turn=False,
        issue_category="Thanh toán-IBFT",
        app="241 - Chuyển Tiền ATM",
        product_code="TF007 - IBFT",
        skill=None,
        intent=None,
        tpe_code=None,
        tpe_status=None,
        guardrail_rule=None,
        transfer_reason="skill_suggested_transfer" if transferred else None,
        escalation_guard_blocked=False,
        csat_satisfaction=None,
        data_quality="valid",
    )


def _conversation(
    conversation_id: int,
    author_id: int | None,
    *,
    incoming: bool = False,
    private: bool = False,
    source: int = 0,
    category: int | None = 3,
) -> ConversationMetadata:
    return ConversationMetadata(
        conversation_id=conversation_id,
        author_id=author_id,
        incoming=incoming,
        private=private,
        source=source,
        created_at=f"2026-08-03T01:0{conversation_id}:00Z",
        category=category,
    )


def _freshdesk_ticket() -> FreshdeskTicketMetadata:
    return FreshdeskTicketMetadata(
        ticket_id="123",
        created_at="2026-08-03T01:00:00Z",
    )


@pytest.mark.parametrize(
    ("langfuse", "conversations", "expected", "human_replied"),
    [
        (_ticket(ai_first=True, transferred=False), (), "ai_replied_only", None),
        (_ticket(ai_first=True, transferred=True), (), "ai_replied_then_transferred", None),
        (_ticket(ai_first=False, transferred=True), (), "transferred_without_ai_reply", None),
        (_ticket(ai_first=False, transferred=False), (_conversation(1, HUMAN),), "invoked_no_result", True),
        (_ticket(ai_first=False, transferred=False), (), "invoked_no_result", False),
    ],
)
def test_matched_langfuse_ticket_states_stay_distinct(
    langfuse: TicketRow,
    conversations: tuple[ConversationMetadata, ...],
    expected: EntryCoverageStatus,
    human_replied: bool | None,
):
    result = classify_entry_coverage(_freshdesk_ticket(), langfuse, conversations, _config())
    assert result.status == expected
    assert result.human_replied is human_replied


def test_classify_entry_coverage_requires_a_known_langfuse_ticket():
    """Population is Langfuse-scoped now (PO, 2026-09-07); a ticket the
    caller can't attach a `TicketRow` to is a caller bug, not a status."""

    with pytest.raises(FreshdeskEntryCoverageError):
        classify_entry_coverage(_freshdesk_ticket(), None, (), _config())


def test_matched_invoked_no_result_unknown_outgoing_stays_matched():
    result = classify_entry_coverage(
        _freshdesk_ticket(),
        _ticket(ai_first=False, transferred=False),
        (_conversation(1, UNKNOWN),),
        _config(),
    )
    assert result.status == "invoked_no_result"
    assert result.human_replied is None


def test_freshdesk_ticket_metadata_is_strict_and_does_not_keep_extra_fields():
    ticket = FreshdeskTicketMetadata(ticket_id="123", created_at="2026-08-03T01:00:00Z")
    assert asdict(ticket) == {
        "ticket_id": "123",
        "created_at": "2026-08-03T01:00:00Z",
        "ai_review_rating_raw": None,
        "ai_review_count_raw": None,
        "ai_review_date_raw": None,
        "ai_reopen_status_raw": None,
        "ai_user_replied_raw": None,
    }
    with pytest.raises(FreshdeskEntryCoverageError):
        FreshdeskTicketMetadata(ticket_id="01", created_at="2026-08-03T01:00:00Z")
    with pytest.raises(FreshdeskEntryCoverageError):
        FreshdeskTicketMetadata(ticket_id="123", created_at="2026-08-03T01:00:00")


def test_list_ticket_metadata_paginates_and_projects_only_id_and_created_at():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = request.url.params["page"]
        if page == "1":
            rows = [
                {
                    "id": 123 + index,
                    "created_at": "2026-08-03T01:00:00Z",
                    "source": 2,
                    "subject": "PRIVATE",
                    "requester_id": 99,
                    "description": "PRIVATE",
                }
                for index in range(100)
            ]
        else:
            rows = [{"id": 456, "created_at": "2026-08-04T01:00:00Z", "source": 3}]
        return httpx.Response(200, json=rows)

    with FreshdeskClient(
        FreshdeskSettings("https://vngzalopay.freshdesk.com", "secret"),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 8, 2, 17, tzinfo=timezone.utc),
        )

    assert len(result) == 101
    assert result[0] == FreshdeskTicketMetadata("123", "2026-08-03T01:00:00Z")
    assert result[-1] == FreshdeskTicketMetadata("456", "2026-08-04T01:00:00Z")
    assert requests[0].url.path == "/api/v2/tickets"
    assert requests[0].url.params["per_page"] == "50"
    assert requests[0].url.params["order_by"] == "updated_at"
    assert requests[0].url.params["order_type"] == "asc"
    assert "include" not in requests[0].url.params
    assert "PRIVATE" not in json.dumps([asdict(item) for item in result])


def test_list_ticket_metadata_rejects_invalid_shape_and_page_limit():
    def invalid_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 123}])

    with FreshdeskClient(
        FreshdeskSettings("https://vngzalopay.freshdesk.com", "secret"),
        transport=httpx.MockTransport(invalid_handler),
    ) as client:
        with pytest.raises(FreshdeskCSATError, match="Freshdesk ticket response"):
            client.list_ticket_metadata(
                updated_since=datetime(2026, 8, 2, 17, tzinfo=timezone.utc),
            )


def test_list_ticket_metadata_uses_stable_small_pages_after_deep_page_500():
    requests: list[tuple[str, str]] = []
    rows = [
        {"id": 1000 + index, "created_at": "2026-08-03T01:00:00Z"}
        for index in range(101)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        page_size = request.url.params["per_page"]
        requests.append((page, page_size))
        if page_size == "100" and page == "2":
            return httpx.Response(500, json={"error": "server-side page failure"})
        size = int(page_size)
        start = (int(page) - 1) * size
        return httpx.Response(200, json=rows[start : start + size])

    with FreshdeskClient(
        FreshdeskSettings("https://vngzalopay.freshdesk.com", "secret"),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 8, 2, 17, tzinfo=timezone.utc),
        )

    assert len(result) == 101
    assert len(result) == 101
    assert all(page_size == "50" for _, page_size in requests)


def test_list_ticket_metadata_resumes_from_checkpoint_page():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        requests.append(page)
        rows = [{"id": 1000 + int(page), "created_at": "2026-07-06T01:00:00Z"}]
        return httpx.Response(200, json=rows)

    with FreshdeskClient(
        FreshdeskSettings("https://vngzalopay.freshdesk.com", "secret"),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 7, 5, 17, tzinfo=timezone.utc),
            start_page=4,
            existing=(FreshdeskTicketMetadata("1001", "2026-07-06T01:00:00Z"),),
        )

    assert requests == ["4"]
    assert [item.ticket_id for item in result] == ["1001", "1004"]


def test_list_ticket_metadata_resumes_past_prior_call_page_budget():
    """A checkpoint resume from page 301 (the boundary exposed 2026-08-12)
    must still fetch, not immediately raise the page-limit error."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        requests.append(page)
        rows = [{"id": 1000 + int(page), "created_at": "2026-07-06T01:00:00Z"}]
        return httpx.Response(200, json=rows)

    with FreshdeskClient(
        FreshdeskSettings("https://vngzalopay.freshdesk.com", "secret"),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 7, 5, 17, tzinfo=timezone.utc),
            start_page=301,
        )

    assert requests == ["301"]
    assert [item.ticket_id for item in result] == ["1301"]
