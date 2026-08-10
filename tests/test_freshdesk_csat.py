from __future__ import annotations

import stat
from datetime import date, datetime, timezone
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from weekly_cs_report.freshdesk_csat import (
    FreshdeskCSATError,
    FreshdeskClient,
    FreshdeskSettings,
    collect_ticket_ratings,
    fetch_csat_population,
    load_agent_config,
    redact_survey_comment,
    resolve_exact_agent_id,
    write_approved_agent_config,
)
from weekly_cs_report.outcome_reconciliation import ConversationMetadata
from weekly_cs_report.csat_cache import (
    CSATCache,
    CSATCacheStats,
    CachedCSATResponse,
)


def _ticket_fields(*choices: dict[str, int]) -> list[dict[str, object]]:
    return [
        {
            "type": "default_agent",
            "name": "agent",
            "choices": choice,
        }
        for choice in choices
    ]


def test_discover_agents_requires_exactly_one_active_name_match():
    fields = _ticket_fields(
        {"Admin CS ZaloPay": 73_001, "Human CS": 73_002},
    )

    assert resolve_exact_agent_id(fields, "Admin CS ZaloPay") == 73_001

    with pytest.raises(FreshdeskCSATError, match="resolve uniquely"):
        resolve_exact_agent_id(fields, "admin cs zalopay")

    with pytest.raises(FreshdeskCSATError, match="resolve uniquely"):
        resolve_exact_agent_id(
            _ticket_fields(
                {"Admin CS ZaloPay": 73_001},
                {"Admin CS ZaloPay": 73_003},
            ),
            "Admin CS ZaloPay",
        )


@pytest.mark.parametrize(
    "field",
    [
        {
            "type": "default_agent",
            "name": "custom_agent",
            "choices": {"Admin CS ZaloPay": 73_001},
        },
        {
            "type": "custom_text",
            "name": "agent",
            "choices": {"Admin CS ZaloPay": 73_001},
        },
    ],
)
def test_discover_agents_rejects_partial_default_agent_field_match(field):
    with pytest.raises(FreshdeskCSATError, match="resolve uniquely"):
        resolve_exact_agent_id([field], "Admin CS ZaloPay")


def test_approved_agent_config_is_private_strict_and_round_trips(tmp_path: Path):
    destination = tmp_path / "private" / "freshdesk_agents.v1.json"

    write_approved_agent_config(
        destination,
        bot_agent_id=73_001,
        approved_at=date(2026, 8, 2),
        survey_scales={
            "43000076179": {
                "positive": (103,),
                "neutral": (100,),
                "negative": (-103,),
            }
        },
    )

    config = load_agent_config(destination)
    assert config.bot_agent_ids == frozenset({73_001})
    assert config.bucket_for(43000076179, 103) == "positive"
    assert config.bucket_for(43000076179, 100) == "neutral"
    assert config.bucket_for(43000076179, -103) == "negative"
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600

    with pytest.raises(FreshdeskCSATError, match="not approved"):
        config.bucket_for(43000076180, 103)
    with pytest.raises(FreshdeskCSATError, match="not approved"):
        config.bucket_for(43000076179, 0)


def test_approved_agent_config_preserves_existing_shared_directory_mode(
    tmp_path: Path,
):
    parent = tmp_path / "shared-config"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)

    write_approved_agent_config(
        parent / "freshdesk_agents.v1.json",
        bot_agent_id=73_001,
        approved_at=date(2026, 8, 2),
        survey_scales={
            "43000076179": {
                "positive": (103,),
                "neutral": (100,),
                "negative": (-103,),
            }
        },
    )

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755


def test_freshdesk_settings_rejects_non_approved_https_origin():
    with pytest.raises(FreshdeskCSATError, match="settings are invalid"):
        FreshdeskSettings(
            base_url="https://support.example.test",
            api_key="test-secret",
        )


def test_csat_fetch_honours_retry_after_and_keeps_only_approved_bot_rows():
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.method == "GET"
        if request.url.path == "/api/v2/tickets/123/conversations":
            return httpx.Response(200, json=[])
        assert request.url.path == "/api/v2/tickets/123/satisfaction_ratings"
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                text="PRIVATE-RATE-LIMIT-BODY",
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": 9001,
                    "ticket_id": 123,
                    "survey_id": 43000076179,
                    "agent_id": 73_001,
                    "created_at": "2026-07-21T04:15:00Z",
                    "ratings": {"default_question": 103},
                    "feedback": "Hài lòng, email private@example.test",
                },
                {
                    "id": 9002,
                    "ticket_id": 123,
                    "survey_id": 43000076179,
                    "agent_id": 73_002,
                    "created_at": "2026-07-21T04:16:00Z",
                    "ratings": {"default_question": -103},
                    "feedback": "PRIVATE HUMAN COMMENT",
                },
                {
                    "id": 9003,
                    "ticket_id": 123,
                    "survey_id": 43000076179,
                    "agent_id": None,
                    "created_at": "2026-07-21T04:17:00Z",
                    "ratings": {"default_question": 100},
                    "feedback": "PRIVATE NULL COMMENT",
                },
            ],
        )

    settings = FreshdeskSettings(
        base_url="https://vngzalopay.freshdesk.com",
        api_key="test-secret",
    )
    config = load_agent_config_from_values()
    with FreshdeskClient(
        settings,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    ) as client:
        result = collect_ticket_ratings(client, ("123",), config)

    assert sleeps == [2.0]
    assert result.stats.all_response_count == 3
    assert result.stats.included_bot_response_count == 1
    assert result.stats.excluded_other_agent_response_count == 1
    assert result.stats.excluded_null_agent_response_count == 1
    assert len(result.responses) == 1
    response = result.responses[0]
    assert response.ticket_id == "123"
    assert response.satisfaction_bucket == "positive"
    assert response.comment_present is True
    assert response.comment_redacted == "Hài lòng, email [đã ẩn]"
    serialized = str(asdict(response))
    assert "agent_id" not in serialized
    assert "private@example.test" not in serialized
    assert "9001" not in serialized


def test_null_agent_survey_uses_immediately_preceding_public_bot_response():
    class FakeClient:
        def get_satisfaction_ratings(self, _ticket_id: str):
            return (
                {
                    "id": 9010,
                    "ticket_id": 123,
                    "survey_id": 43000076179,
                    "agent_id": None,
                    "created_at": "2026-07-21T04:17:00Z",
                    "ratings": {"default_question": 103},
                    "feedback": "Rất hài lòng",
                },
            )

        def get_conversation_metadata(self, _ticket_id: str):
            return (
                ConversationMetadata(
                    conversation_id=1,
                    author_id=73_001,
                    incoming=False,
                    private=False,
                    source=0,
                    created_at="2026-07-21T04:16:00Z",
                ),
                ConversationMetadata(
                    conversation_id=2,
                    author_id=73_002,
                    incoming=True,
                    private=False,
                    source=6,
                    created_at="2026-07-21T04:16:30Z",
                ),
            )

    result = collect_ticket_ratings(
        FakeClient(),
        ("123",),
        load_agent_config_from_values(),
    )

    assert len(result.responses) == 1
    assert result.responses[0].satisfaction_bucket == "positive"
    assert result.stats.excluded_null_agent_response_count == 0


def test_null_agent_survey_is_not_rescued_by_an_earlier_bot_response():
    class FakeClient:
        def get_satisfaction_ratings(self, _ticket_id: str):
            return (
                {
                    "id": 9011,
                    "ticket_id": 123,
                    "survey_id": 43000076179,
                    "agent_id": None,
                    "created_at": "2026-07-21T04:17:00Z",
                    "ratings": {"default_question": 103},
                    "feedback": "Rất hài lòng",
                },
            )

        def get_conversation_metadata(self, _ticket_id: str):
            return (
                ConversationMetadata(
                    conversation_id=1,
                    author_id=73_001,
                    incoming=False,
                    private=False,
                    source=0,
                    created_at="2026-07-21T04:16:00Z",
                ),
                ConversationMetadata(
                    conversation_id=2,
                    author_id=73_002,
                    incoming=False,
                    private=False,
                    source=0,
                    created_at="2026-07-21T04:16:30Z",
                ),
            )

    result = collect_ticket_ratings(
        FakeClient(),
        ("123",),
        load_agent_config_from_values(),
    )

    assert result.responses == ()
    assert result.stats.excluded_null_agent_response_count == 1


def test_freshdesk_client_waits_through_a_rolling_hour_rate_limit():
    attempts = 0
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts <= 11:
            return httpx.Response(
                429,
                headers={"Retry-After": "300"},
                text="PRIVATE-RATE-LIMIT-BODY",
            )
        return httpx.Response(200, json=[])

    settings = FreshdeskSettings(
        base_url="https://vngzalopay.freshdesk.com",
        api_key="test-secret",
    )
    with FreshdeskClient(
        settings,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    ) as client:
        assert client.get_satisfaction_ratings("123") == ()

    assert attempts == 12
    assert sleeps == [300.0] * 11


def test_csat_fetch_fails_closed_for_unapproved_rating_without_leaking_body():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/tickets/123/conversations":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {
                    "id": 9010,
                    "ticket_id": 123,
                    "survey_id": 43000076179,
                    "agent_id": 73_001,
                    "created_at": "2026-07-21T04:15:00Z",
                    "ratings": {"default_question": 999},
                    "feedback": "PRIVATE-MARKER",
                }
            ],
        )

    with FreshdeskClient(
        FreshdeskSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="test-secret",
        ),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(FreshdeskCSATError, match="not approved") as error:
            collect_ticket_ratings(client, ("123",), load_agent_config_from_values())

    assert "PRIVATE-MARKER" not in str(error.value)
    assert "test-secret" not in str(error.value)


def load_agent_config_from_values():
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


def test_incremental_fetch_skips_frozen_week_and_refreshes_late_response_window():
    requested: list[str] = []

    class FakeClient:
        def get_satisfaction_ratings(self, ticket_id: str):
            requested.append(ticket_id)
            return (
                {
                    "id": int(ticket_id) + 90_000,
                    "ticket_id": int(ticket_id),
                    "survey_id": 43000076179,
                    "agent_id": 73_001,
                    "created_at": "2026-08-02T01:00:00Z",
                    "ratings": {"default_question": 103},
                    "feedback": None,
                },
            )

    existing = CSATCache(
        fetched_weeks={
            "2026-06-29": "2026-07-06T01:00:00Z",
            "2026-07-20": "2026-07-27T01:00:00Z",
        },
        fetch_stats=CSATCacheStats(
            all_response_count=1,
            included_bot_response_count=1,
            excluded_other_agent_response_count=0,
            excluded_null_agent_response_count=0,
        ),
        responses=(
            CachedCSATResponse(
                response_key=f"sha256:{'a' * 64}",
                ticket_id="101",
                survey_id=43000076179,
                responded_at="2026-07-01T01:00:00Z",
                rating_raw=103,
                satisfaction_bucket="positive",
                comment_present=False,
                comment_redacted=None,
            ),
        ),
    )

    result = fetch_csat_population(
        FakeClient(),
        {
            "2026-06-29": ("101",),
            "2026-07-20": ("202",),
            "2026-07-27": ("303",),
        },
        load_agent_config_from_values(),
        existing=existing,
        as_of=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        max_workers=1,
    )

    assert requested == ["202", "303"]
    assert result.completed_weeks == ("2026-07-20", "2026-07-27")
    assert result.complete is True
    assert {item.ticket_id for item in result.cache.responses} == {
        "101",
        "202",
        "303",
    }


def test_unknown_rating_does_not_mutate_last_good_cache():
    class FakeClient:
        def get_satisfaction_ratings(self, ticket_id: str):
            return (
                {
                    "id": 99_999,
                    "ticket_id": int(ticket_id),
                    "survey_id": 43000076179,
                    "agent_id": 73_001,
                    "created_at": "2026-08-02T01:00:00Z",
                    "ratings": {"default_question": 999},
                    "feedback": "PRIVATE",
                },
            )

    existing = CSATCache(
        fetched_weeks={},
        fetch_stats=CSATCacheStats(0, 0, 0, 0),
        responses=(),
    )

    with pytest.raises(FreshdeskCSATError, match="not approved"):
        fetch_csat_population(
            FakeClient(),
            {"2026-07-27": ("303",)},
            load_agent_config_from_values(),
            existing=existing,
            as_of=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
            max_workers=1,
        )

    assert existing.responses == ()
    assert existing.fetched_weeks == {}


def test_fetch_emits_completed_week_checkpoint_before_later_week_failure():
    checkpoints: list[CSATCache] = []

    class FakeClient:
        def get_satisfaction_ratings(self, ticket_id: str):
            if ticket_id == "202":
                raise FreshdeskCSATError("Freshdesk request failed")
            return (
                {
                    "id": 91_101,
                    "ticket_id": int(ticket_id),
                    "survey_id": 43000076179,
                    "agent_id": 73_001,
                    "created_at": "2026-08-02T01:00:00Z",
                    "ratings": {"default_question": 103},
                    "feedback": None,
                },
            )

    with pytest.raises(FreshdeskCSATError, match="request failed"):
        fetch_csat_population(
            FakeClient(),
            {
                "2026-07-20": ("101",),
                "2026-07-27": ("202",),
            },
            load_agent_config_from_values(),
            existing=None,
            as_of=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
            max_workers=1,
            on_week_complete=checkpoints.append,
        )

    assert len(checkpoints) == 1
    assert set(checkpoints[0].fetched_weeks) == {"2026-07-20"}
    assert [item.ticket_id for item in checkpoints[0].responses] == ["101"]


def test_fetch_stops_during_a_week_without_checkpointing_partial_results():
    requested: list[str] = []
    checkpoints: list[CSATCache] = []
    clock = iter((0.0, 0.0, 0.5, 1.1))

    class FakeClient:
        def get_satisfaction_ratings(self, ticket_id: str):
            requested.append(ticket_id)
            return ()

    result = fetch_csat_population(
        FakeClient(),
        {"2026-07-27": ("101", "102")},
        load_agent_config_from_values(),
        existing=None,
        as_of=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        max_workers=1,
        max_duration_seconds=1,
        monotonic=lambda: next(clock),
        on_week_complete=checkpoints.append,
    )

    assert result.complete is False
    assert result.completed_weeks == ()
    assert result.cache.fetched_weeks == {}
    assert result.cache.responses == ()
    assert requested == ["101"]
    assert checkpoints == []


def test_fetch_resumes_a_partial_run_without_refetching_weeks_just_checkpointed():
    requested: list[str] = []

    class FakeClient:
        def get_satisfaction_ratings(self, ticket_id: str):
            requested.append(ticket_id)
            return ()

    existing = CSATCache(
        fetched_weeks={
            "2026-07-20": "2026-08-07T10:39:23Z",
            "2026-07-27": "2026-08-07T10:39:23Z",
        },
        fetch_stats=CSATCacheStats(0, 0, 0, 0),
        responses=(),
    )

    result = fetch_csat_population(
        FakeClient(),
        {
            "2026-07-20": ("101",),
            "2026-07-27": ("202",),
            "2026-08-03": ("303",),
        },
        load_agent_config_from_values(),
        existing=existing,
        as_of=datetime(2026, 8, 7, 11, tzinfo=timezone.utc),
        max_workers=1,
    )

    assert result.complete is True
    assert result.completed_weeks == ("2026-08-03",)
    assert requested == ["303"]


@pytest.mark.parametrize(
    "comment",
    [
        "sdt cua e la 0 9 0 1 2 3 4 5 6 7",
        "email customer@example.test va https://example.test/ticket/123",
        "ma giao dich 1234567890123456",
        "Nguyễn Văn An hỗ trợ rất tốt",
    ],
)
def test_survey_comment_redaction_removes_pii_patterns(comment: str):
    redacted = redact_survey_comment(comment)

    assert redacted is not None
    assert comment not in redacted
    assert "0901234567" not in "".join(character for character in redacted if character.isdigit())
    assert "example.test" not in redacted
    assert "1234567890123456" not in redacted
    assert "Nguyễn Văn An" not in redacted
    assert len(redacted) <= 200


def test_survey_comment_redaction_returns_none_for_blank_and_caps_length():
    assert redact_survey_comment("   ") is None
    assert len(redact_survey_comment("x" * 500) or "") == 200


@pytest.mark.parametrize(
    "comment",
    [
        "Xem example.test/help?token=private",
        "Xem vídụ.vn/help?token=private",
        "Xem 192.168.1.1/help?token=private",
        "Xem [2001:db8::1]/help?token=private",
        "Xem 2001:db8::1/help?token=private",
        "Xem zalo://open/ticket/12345",
        "Xem zalo:open/ticket/12345",
    ],
)
def test_survey_comment_redaction_removes_bare_url(comment: str):
    assert redact_survey_comment(comment) == "Xem [đã ẩn]"


@pytest.mark.parametrize(
    "comment",
    [
        "xử lý lâu",
        "xử lý không tốt",
        "CS xử lý nhanh và rõ ràng",
        "lý do xử lý chậm",
        "hồ sơ chưa hoàn tất",
    ],
)
def test_survey_comment_redaction_preserves_non_pii_phrases(comment: str):
    assert redact_survey_comment(comment) == comment
