from __future__ import annotations

import json
import stat
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from weekly_cs_report.freshdesk_csat import (
    FreshdeskCSATError,
    FreshdeskCookieExpired,
    FreshdeskCookieMissing,
    FreshdeskUIClient,
    collect_ticket_ratings,
    cookie_path,
    cookie_state_path,
    load_freshdesk_cookie,
    mark_cookie_expired,
    mark_cookie_verified,
    read_cookie_state,
    write_freshdesk_cookie,
)
from weekly_cs_report.freshdesk_entry_coverage import FreshdeskTicketMetadata


def _agent_config():
    from weekly_cs_report.freshdesk_csat import FreshdeskAgentConfig

    return FreshdeskAgentConfig(
        bot_agent_ids=frozenset({73_001}),
        survey_scales={
            "43000076179": {
                "positive": (103,),
                "neutral": (100,),
                "negative": (-103,),
            }
        },
    )


# --- FreshdeskUIClient: transport shape ------------------------------------


def test_ui_client_satisfaction_ratings_unwraps_dict_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/api/_/tickets/123/conversations":
            return httpx.Response(200, json={"conversations": [], "meta": {"count": 0}})
        assert request.url.path == "/api/_/tickets/123/satisfaction_ratings"
        return httpx.Response(
            200,
            json={
                "satisfaction_ratings": [
                    {
                        "id": 9001,
                        "ticket_id": 123,
                        "survey_id": 43000076179,
                        "agent_id": 73_001,
                        "created_at": "2026-07-21T04:15:00Z",
                        "ratings": {"default_question": 103},
                        "feedback": "Hài lòng, email private@example.test",
                        "group_id": 55,
                        "user_id": 999,
                        "updated_at": "2026-07-21T04:15:00Z",
                    }
                ]
            },
        )

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        result = collect_ticket_ratings(client, ("123",), _agent_config())

    assert result.stats.all_response_count == 1
    assert result.stats.included_bot_response_count == 1
    assert len(result.responses) == 1
    assert result.responses[0].satisfaction_bucket == "positive"


def test_ui_client_rejects_ratings_response_missing_the_wrapper_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": []})

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(FreshdeskCSATError, match="rating response is invalid"):
            client.get_satisfaction_ratings("123")


def test_ui_client_conversations_projects_only_approved_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "conversations": [
                    {
                        "id": 501,
                        "user_id": 73_001,
                        "incoming": False,
                        "private": False,
                        "source": 0,
                        "created_at": "2026-07-21T04:00:00Z",
                        "category": 3,
                        "body": "PRIVATE BODY TEXT",
                        "body_text": "PRIVATE BODY TEXT",
                        "from_email": "private@example.test",
                    }
                ],
                "meta": {"count": 1},
            },
        )

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        rows = client.get_conversation_metadata("123")

    assert len(rows) == 1
    row = rows[0]
    assert row.conversation_id == 501
    assert row.author_id == 73_001
    assert row.category == 3
    serialized = str(row)
    assert "private@example.test" not in serialized
    assert "PRIVATE BODY TEXT" not in serialized


def test_ui_client_conversations_fail_closed_when_meta_count_disagrees():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"conversations": [{"id": 1}], "meta": {"count": 2}},
        )

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(FreshdeskCSATError, match="incomplete"):
            client.get_conversation_metadata("123")


@pytest.mark.parametrize("status_code", [401, 403])
def test_ui_client_expired_cookie_raises_cookie_expired(status_code: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="login page")

    with FreshdeskUIClient(
        "cs_session=stale", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(FreshdeskCookieExpired):
            client.get_satisfaction_ratings("123")


def test_ui_client_honours_retry_after_before_succeeding():
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"satisfaction_ratings": []})

    with FreshdeskUIClient(
        "cs_session=abc123",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    ) as client:
        result = client.get_satisfaction_ratings("123")

    assert sleeps == [3.0]
    assert result == ()


def test_ui_client_rejects_blank_cookie():
    with pytest.raises(FreshdeskCSATError, match="cookie is invalid"):
        FreshdeskUIClient("   ")


def test_ui_client_never_leaks_cookie_in_transcript_via_repr():
    client = FreshdeskUIClient(
        "cs_session=super-secret-value",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    try:
        assert "super-secret-value" not in repr(client)
    finally:
        client.close()


# --- FreshdeskUIClient.list_ticket_metadata --------------------------------


def test_ui_list_ticket_metadata_paginates_and_projects_only_id_and_created_at():
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
                for index in range(50)
            ]
        else:
            rows = [{"id": 456, "created_at": "2026-08-04T01:00:00Z", "source": 3}]
        return httpx.Response(200, json={"tickets": rows})

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 8, 2, 17, tzinfo=timezone.utc),
        )

    assert len(result) == 51
    assert result[0] == FreshdeskTicketMetadata("123", "2026-08-03T01:00:00Z")
    assert result[-1] == FreshdeskTicketMetadata("456", "2026-08-04T01:00:00Z")
    assert requests[0].url.path == "/api/_/tickets"
    assert requests[0].url.params["per_page"] == "50"
    assert requests[0].url.params["order_by"] == "created_at"
    assert requests[0].url.params["order_type"] == "asc"
    assert requests[0].url.params["query_hash[0][condition]"] == "created_at"
    assert "PRIVATE" not in json.dumps([asdict(item) for item in result])


def test_ui_list_ticket_metadata_rejects_response_missing_tickets_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": []})

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(FreshdeskCSATError, match="Freshdesk ticket response"):
            client.list_ticket_metadata(
                updated_since=datetime(2026, 8, 2, 17, tzinfo=timezone.utc),
            )


def test_ui_list_ticket_metadata_rejects_invalid_row_shape():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tickets": [{"id": 123}]})

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(FreshdeskCSATError, match="Freshdesk ticket response"):
            client.list_ticket_metadata(
                updated_since=datetime(2026, 8, 2, 17, tzinfo=timezone.utc),
            )


def test_ui_list_ticket_metadata_resumes_from_checkpoint_page():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        requests.append(page)
        rows = [{"id": 1000 + int(page), "created_at": "2026-07-06T01:00:00Z"}]
        return httpx.Response(200, json={"tickets": rows})

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 7, 5, 17, tzinfo=timezone.utc),
            start_page=7,
            existing=(FreshdeskTicketMetadata("1", "2026-07-01T00:00:00Z"),),
        )

    assert requests[0] == "7"
    assert len(result) == 2
    assert result[0].ticket_id == "1"


def test_ui_list_ticket_metadata_resumes_past_prior_call_page_budget():
    """A checkpoint resume from page 301 (the boundary exposed 2026-08-12)
    must still fetch, not immediately raise the page-limit error."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        requests.append(page)
        rows = [{"id": 1000 + int(page), "created_at": "2026-07-06T01:00:00Z"}]
        return httpx.Response(200, json={"tickets": rows})

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 7, 5, 17, tzinfo=timezone.utc),
            start_page=301,
        )

    assert requests == ["301"]
    assert [item.ticket_id for item in result] == ["1301"]


def test_ui_list_ticket_metadata_rejects_duplicate_tickets_across_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        rows = [{"id": 999, "created_at": "2026-07-06T01:00:00Z"}]
        return httpx.Response(200, json={"tickets": rows})

    with FreshdeskUIClient(
        "cs_session=abc123", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(FreshdeskCSATError, match="duplicate"):
            client.list_ticket_metadata(
                updated_since=datetime(2026, 7, 5, 17, tzinfo=timezone.utc),
                existing=(FreshdeskTicketMetadata("999", "2026-07-06T00:00:00Z"),),
            )


# --- cookie file storage -----------------------------------------------------


def test_load_freshdesk_cookie_prefers_file_over_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FRESHDESK_COOKIE", "env-value-should-not-win")
    write_freshdesk_cookie(tmp_path, "file-value")
    assert load_freshdesk_cookie(tmp_path) == "file-value"


def test_load_freshdesk_cookie_falls_back_to_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FRESHDESK_COOKIE", "env-value")
    assert load_freshdesk_cookie(tmp_path) == "env-value"


def test_load_freshdesk_cookie_raises_when_neither_present(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FRESHDESK_COOKIE", raising=False)
    with pytest.raises(FreshdeskCookieMissing):
        load_freshdesk_cookie(tmp_path)


def test_write_freshdesk_cookie_sets_private_mode(tmp_path: Path):
    write_freshdesk_cookie(tmp_path, "cs_session=abc123")
    path = cookie_path(tmp_path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    dir_mode = stat.S_IMODE(path.parent.stat().st_mode)
    assert dir_mode == 0o700
    assert path.read_text(encoding="utf-8") == "cs_session=abc123"


def test_write_freshdesk_cookie_rejects_blank_value(tmp_path: Path):
    with pytest.raises(FreshdeskCSATError, match="cookie value is invalid"):
        write_freshdesk_cookie(tmp_path, "   ")


def test_read_cookie_state_returns_missing_synthetic_default(tmp_path: Path):
    state = read_cookie_state(tmp_path)
    assert state["state"] == "missing"
    assert state["last_verified_at"] is None


def test_read_cookie_state_rejects_malformed_file(tmp_path: Path):
    cookie_state_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    cookie_state_path(tmp_path).write_text("not json", encoding="utf-8")
    with pytest.raises(FreshdeskCSATError, match="cookie state is invalid"):
        read_cookie_state(tmp_path)


def test_mark_cookie_verified_then_expired_round_trips(tmp_path: Path):
    mark_cookie_verified(tmp_path)
    state = read_cookie_state(tmp_path)
    assert state["state"] == "ok"
    assert state["last_verified_at"] is not None
    first_verified_at = state["last_verified_at"]

    mark_cookie_expired(tmp_path)
    state = read_cookie_state(tmp_path)
    assert state["state"] == "expired"
    assert state["last_failure_at"] is not None
    # Verifying again after expiry must not lose the last-known-good timestamp
    # of the expiry event once we go back to ok.
    mark_cookie_verified(tmp_path)
    state = read_cookie_state(tmp_path)
    assert state["state"] == "ok"
    assert state["last_failure_at"] is not None
    assert state["last_verified_at"] != first_verified_at


def test_cookie_state_file_is_private_mode(tmp_path: Path):
    mark_cookie_verified(tmp_path)
    mode = stat.S_IMODE(cookie_state_path(tmp_path).stat().st_mode)
    assert mode == 0o600
