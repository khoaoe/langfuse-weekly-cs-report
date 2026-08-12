from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json

import httpx
import pytest

from weekly_cs_report.dashboard_schema import TicketRow
from weekly_cs_report.entry_coverage_cache import (
    EntryCoverageCache,
    EntryCoverageRecord,
)
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
    fetch_entry_coverage_population,
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


@pytest.mark.parametrize(
    ("conversations", "expected", "human_replied"),
    [
        ((_conversation(1, HUMAN),), "not_observed_invoked", True),
        ((), "not_observed_invoked", False),
        ((_conversation(1, BOT),), "unresolved", None),
        ((_conversation(1, UNKNOWN),), "unresolved", None),
        ((_conversation(1, EXCLUDED),), "not_observed_invoked", False),
        ((_conversation(1, HUMAN, incoming=True),), "not_observed_invoked", False),
        ((_conversation(1, HUMAN, private=True),), "not_observed_invoked", False),
        ((_conversation(1, HUMAN, source=6),), "not_observed_invoked", False),
    ],
)
def test_unmatched_ticket_states_do_not_merge_invoked_no_result(
    conversations: tuple[ConversationMetadata, ...],
    expected: EntryCoverageStatus,
    human_replied: bool | None,
):
    result = classify_entry_coverage(_freshdesk_ticket(), None, conversations, _config())
    assert result.status == expected
    assert result.human_replied is human_replied


@pytest.mark.parametrize("category", [1, 2, 5, 7])
def test_non_agent_conversation_categories_do_not_count_as_public_replies(category: int):
    result = classify_entry_coverage(
        _freshdesk_ticket(),
        None,
        (_conversation(1, HUMAN, category=category),),
        _config(),
    )
    assert result.status == "not_observed_invoked"
    assert result.human_replied is False


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


def test_incremental_entry_coverage_skips_records_already_checkpointed():
    tickets = (
        FreshdeskTicketMetadata("123", "2026-07-06T01:00:00Z"),
        FreshdeskTicketMetadata("456", "2026-07-06T02:00:00Z"),
    )
    resumed = EntryCoverageRecord(
        ticket_id="123",
        opened_at="2026-07-06T01:00:00Z",
        cohort_week="2026-07-06",
        status="invoked_no_result",
        human_replied=False,
    )
    calls: list[str] = []

    class Client:
        def get_conversation_metadata(self, ticket_id: str, *, should_stop=None):
            calls.append(ticket_id)
            return (_conversation(1, HUMAN),)

    result = fetch_entry_coverage_population(
        Client(),
        tickets,
        {},
        ("2026-07-06",),
        _config(),
        existing=EntryCoverageCache(fetched_weeks={}, records=()),
        resume_records=(resumed,),
        resume_week="2026-07-06",
        resume_index=1,
        as_of=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
        max_workers=1,
    )

    assert result.complete is True
    assert calls == ["456"]
    assert {item.ticket_id for item in result.cache.records} == {"123", "456"}


def test_incremental_entry_coverage_refetches_recent_week_and_keeps_old_week():
    current = FreshdeskTicketMetadata("123", "2026-08-03T01:00:00Z")
    old = EntryCoverageRecord(
        ticket_id="999",
        opened_at="2026-07-13T01:00:00Z",
        cohort_week="2026-07-13",
        status="not_observed_invoked",
        human_replied=False,
    )
    existing = EntryCoverageCache(
        fetched_weeks={"2026-07-13": "2026-08-03T01:00:00Z"},
        records=(old,),
    )
    calls: list[str] = []

    class Client:
        def get_conversation_metadata(self, ticket_id: str, *, should_stop=None):
            calls.append(ticket_id)
            return (_conversation(1, HUMAN),)

    result = fetch_entry_coverage_population(
        Client(),
        (current,),
        {},
        ("2026-07-13", "2026-08-03"),
        _config(),
        existing=existing,
        as_of=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
        max_workers=1,
    )

    assert result.complete is True
    assert result.completed_weeks == ("2026-08-03",)
    assert calls == ["123"]
    assert set(result.cache.fetched_weeks) == {"2026-07-13", "2026-08-03"}
    assert {item.ticket_id for item in result.cache.records} == {"123", "999"}
