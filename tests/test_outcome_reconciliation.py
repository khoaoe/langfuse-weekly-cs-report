from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import stat

import httpx
import pytest

from weekly_cs_report.freshdesk_csat import (
    FreshdeskCSATError,
    FreshdeskClient,
    FreshdeskSettings,
)
from weekly_cs_report.outcome_reconciliation import (
    ConversationMetadata,
    OutcomeReconciliationError,
    ReconciliationAgentConfig,
    approve_reconciliation_candidates,
    classify_human_reply_after_ai,
    fetch_reconciliation_population,
    load_reconciliation_agent_config,
)
from weekly_cs_report.reconciliation_cache import (
    ReconciliationCache,
    ReconciliationRecord,
)


BOT = 10_001
HUMAN = 10_002
EXCLUDED = 10_003
UNKNOWN = 10_004


def _source(path: Path) -> str:
    path.write_text('{"approved":true}', encoding="utf-8")
    path.chmod(0o600)
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _config_value(source_hash: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "approved_by": "PO",
        "approved_at": "2026-08-03",
        "bot_agent_ids": [BOT],
        "human_agent_ids": [HUMAN],
        "excluded_agent_ids": [EXCLUDED],
        "source_hash": source_hash,
    }


def _write_config(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_reconciliation_agent_config_is_private_strict_disjoint_and_source_bound(
    tmp_path: Path,
):
    source = tmp_path / "approved-candidates.json"
    destination = tmp_path / "agents.json"
    source_hash = _source(source)
    _write_config(destination, _config_value(source_hash))

    config = load_reconciliation_agent_config(destination, source_path=source)
    assert config.bot_agent_ids == frozenset({BOT})
    assert config.human_agent_ids == frozenset({HUMAN})
    assert config.excluded_agent_ids == frozenset({EXCLUDED})

    invalid_values = []
    for key in ("source_hash", "human_agent_ids"):
        value = _config_value(source_hash)
        del value[key]
        invalid_values.append(value)
    extra = _config_value(source_hash)
    extra["agent_names"] = ["private"]
    invalid_values.append(extra)
    overlap = _config_value(source_hash)
    overlap["human_agent_ids"] = [BOT]
    invalid_values.append(overlap)
    bad_source = _config_value("sha256:" + "0" * 64)
    invalid_values.append(bad_source)

    for value in invalid_values:
        _write_config(destination, value)
        with pytest.raises(OutcomeReconciliationError):
            load_reconciliation_agent_config(destination, source_path=source)

    _write_config(destination, _config_value(source_hash))
    destination.chmod(0o644)
    with pytest.raises(OutcomeReconciliationError):
        load_reconciliation_agent_config(destination, source_path=source)


def test_candidate_approval_is_conservative_private_and_never_returns_names(
    tmp_path: Path,
):
    source = tmp_path / "candidates.json"
    destination = tmp_path / "agents.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-08-03T01:00:00Z",
                "source": "freshdesk_ticket_fields",
                "status": "pending_review",
                "approved_by": None,
                "approved_at": None,
                "approved_bot_excluded": True,
                "instructions": "synthetic",
                "candidates": [
                    {
                        "agent_id": HUMAN,
                        "display_name": "Phạm Bảo Toàn",
                        "decision": "unreviewed",
                    },
                    {
                        "agent_id": HUMAN + 10,
                        "display_name": "Ngô Thị Bích Ngân",
                        "decision": "unreviewed",
                    },
                    {
                        "agent_id": EXCLUDED,
                        "display_name": "QA Team",
                        "decision": "unreviewed",
                    },
                    {
                        "agent_id": EXCLUDED + 10,
                        "display_name": "Unknown",
                        "decision": "unreviewed",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source.chmod(0o600)

    stats = approve_reconciliation_candidates(
        source,
        destination,
        bot_agent_ids=frozenset({BOT}),
        approved_at=date(2026, 8, 3),
    )

    assert stats == {
        "candidate_count": 4,
        "human_agent_count": 2,
        "excluded_agent_count": 2,
    }
    assert "display_name" not in json.dumps(stats)
    approved = json.loads(source.read_text(encoding="utf-8"))
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "PO"
    assert approved["approved_at"] == "2026-08-03"
    assert {row["decision"] for row in approved["candidates"]} == {
        "human",
        "exclude",
    }
    config = load_reconciliation_agent_config(destination, source_path=source)
    assert config.human_agent_ids == frozenset({HUMAN, HUMAN + 10})
    assert config.excluded_agent_ids == frozenset({EXCLUDED, EXCLUDED + 10})
    assert stat.S_IMODE(source.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def _conversation(
    conversation_id: int,
    author_id: int | None,
    minute: int,
    *,
    incoming: bool = False,
    private: bool = False,
    source: int = 0,
) -> ConversationMetadata:
    return ConversationMetadata(
        conversation_id=conversation_id,
        author_id=author_id,
        incoming=incoming,
        private=private,
        source=source,
        created_at=f"2026-08-03T01:{minute:02d}:00Z",
    )


@pytest.mark.parametrize(
    ("conversations", "expected"),
    [
        ((_conversation(1, BOT, 0), _conversation(2, HUMAN, 1)), True),
        # A requester message never becomes a human-CS reply even if its ID
        # collides with an approved agent identity.
        ((_conversation(1, BOT, 0), _conversation(2, HUMAN, 1, incoming=True)), False),
        ((_conversation(1, HUMAN, 0), _conversation(2, BOT, 1)), False),
        ((_conversation(1, BOT, 0), _conversation(2, HUMAN, 1, private=True)), False),
        ((_conversation(1, BOT, 0), _conversation(2, HUMAN, 1, source=6)), False),
        ((_conversation(1, BOT, 0), _conversation(2, EXCLUDED, 1)), False),
        ((_conversation(1, BOT, 0), _conversation(2, None, 1)), None),
        ((_conversation(1, BOT, 0), _conversation(2, UNKNOWN, 1)), None),
        ((_conversation(1, HUMAN, 0),), None),
        # Equal timestamps use transient conversation ID as a deterministic
        # order: ID 2 is after the bot; ID 1 is before it.
        (
            (
                _conversation(1, BOT, 0),
                _conversation(2, HUMAN, 0),
            ),
            True,
        ),
        (
            (
                _conversation(1, HUMAN, 0),
                _conversation(2, BOT, 0),
            ),
            False,
        ),
    ],
)
def test_classifier_uses_public_agent_identity_and_sequence_only(
    conversations: tuple[ConversationMetadata, ...],
    expected: bool | None,
):
    config = ReconciliationAgentConfig(
        approved_by="PO",
        approved_at="2026-08-03",
        bot_agent_ids=frozenset({BOT}),
        human_agent_ids=frozenset({HUMAN}),
        excluded_agent_ids=frozenset({EXCLUDED}),
        source_hash="sha256:" + "1" * 64,
    )
    assert classify_human_reply_after_ai(conversations, config) is expected


def test_freshdesk_conversation_fetch_projects_metadata_immediately_and_paginates():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": index + 1,
                        "user_id": BOT,
                        "incoming": False,
                        "private": False,
                        "source": 0,
                        "created_at": "2026-08-03T01:00:00Z",
                        "body": "must-not-cross",
                        "body_text": "must-not-cross",
                        "attachments": [{"name": "must-not-cross"}],
                    }
                    for index in range(100)
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": 101,
                    "user_id": HUMAN,
                    "incoming": False,
                    "private": False,
                    "source": 0,
                    "created_at": "2026-08-03T01:01:00Z",
                    "body": "must-not-cross",
                }
            ],
        )

    client = FreshdeskClient(
        FreshdeskSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="synthetic",
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        rows = client.get_conversation_metadata("123")
    finally:
        client.close()

    assert len(rows) == 101
    assert set(asdict(rows[-1])) == {
        "conversation_id",
        "author_id",
        "incoming",
        "private",
        "source",
        "created_at",
        "category",
        "is_autorep_private_note",
    }
    serialized = json.dumps([asdict(row) for row in rows])
    assert "body" not in serialized
    assert "attachments" not in serialized
    assert requests[0].endswith("page=1&per_page=100")
    assert requests[1].endswith("page=2&per_page=100")


def test_freshdesk_conversation_fetch_stops_at_the_page_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json=[
                {
                    "id": page * 100 + index + 1,
                    "user_id": BOT,
                    "incoming": False,
                    "private": False,
                    "source": 0,
                    "created_at": "2026-08-03T01:00:00Z",
                }
                for index in range(100)
            ],
        )

    client = FreshdeskClient(
        FreshdeskSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="synthetic",
        ),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(FreshdeskCSATError, match="conversation page limit exceeded"):
            client.get_conversation_metadata("123")
    finally:
        client.close()


def test_incremental_reconciliation_refetches_recent_week_and_freezes_old_week():
    calls: list[str] = []
    checkpoints: list[ReconciliationCache] = []

    class Client:
        def get_conversation_metadata(self, ticket_id: str):
            calls.append(ticket_id)
            if ticket_id == "202":
                return (_conversation(1, BOT, 0), _conversation(2, HUMAN, 1))
            return (_conversation(1, BOT, 0),)

    config = ReconciliationAgentConfig(
        approved_by="PO",
        approved_at="2026-08-03",
        bot_agent_ids=frozenset({BOT}),
        human_agent_ids=frozenset({HUMAN}),
        excluded_agent_ids=frozenset({EXCLUDED}),
        source_hash="sha256:" + "1" * 64,
    )
    existing = ReconciliationCache(
        fetched_weeks={
            "2026-07-13": "2026-07-20T01:00:00Z",
            "2026-07-20": "2026-07-27T01:00:00Z",
        },
        records=(
            ReconciliationRecord("101", "2026-07-13", False),
            ReconciliationRecord("201", "2026-07-20", True),
        ),
    )

    result = fetch_reconciliation_population(
        Client(),
        {"2026-07-13": ("101",), "2026-07-20": ("201", "202")},
        config,
        existing=existing,
        as_of=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
        max_workers=1,
        on_week_complete=checkpoints.append,
    )

    assert result.complete is True
    assert result.completed_weeks == ("2026-07-20",)
    assert calls == ["201", "202"]
    assert checkpoints == [result.cache]
    assert result.cache.records == (
        ReconciliationRecord("101", "2026-07-13", False),
        ReconciliationRecord("201", "2026-07-20", False),
        ReconciliationRecord("202", "2026-07-20", True),
    )
    serialized = json.dumps(
        [asdict(record) for record in result.cache.records],
        sort_keys=True,
    )
    for forbidden in ("author_id", "conversation_id", "created_at", "body"):
        assert forbidden not in serialized
