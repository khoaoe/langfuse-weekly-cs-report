from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from weekly_cs_report.csat_cache import (
    CSATCache,
    CSATCacheError,
    CSATCacheStats,
    CachedCSATResponse,
    load_csat_cache,
    write_csat_cache,
)


def _response(
    *,
    key: str,
    rating: int,
    bucket: str,
    comment: str | None = "[đã ẩn]",
) -> CachedCSATResponse:
    return CachedCSATResponse(
        response_key=f"sha256:{key * 64}",
        ticket_id="123",
        survey_id=43000076179,
        responded_at="2026-07-21T04:15:00Z",
        rating_raw=rating,
        satisfaction_bucket=bucket,
        comment_present=comment is not None,
        comment_redacted=comment,
    )


def _cache() -> CSATCache:
    return CSATCache(
        fetched_weeks={"2026-07-20": "2026-08-02T01:00:00Z"},
        fetch_stats=CSATCacheStats(
            all_response_count=4,
            included_bot_response_count=2,
            excluded_other_agent_response_count=1,
            excluded_null_agent_response_count=1,
        ),
        responses=(
            _response(key="a", rating=103, bucket="positive"),
            _response(key="b", rating=100, bucket="neutral"),
        ),
    )


def test_csat_cache_is_private_strict_and_keeps_two_responses_per_ticket(tmp_path: Path):
    destination = tmp_path / "runtime" / "csat_cache.json"

    write_csat_cache(destination, _cache())
    loaded = load_csat_cache(destination)

    assert loaded == _cache()
    assert loaded is not None
    assert len(loaded.responses) == 2
    assert {item.ticket_id for item in loaded.responses} == {"123"}
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    serialized = destination.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert payload["schema_version"] == 2
    assert payload["responses"][0]["comment_redacted"] == "[đã ẩn]"
    for forbidden in (
        "agent_id",
        "agent_name",
        "feedback",
        "body_text",
        "raw_comment",
        '"comment":',
    ):
        assert forbidden not in serialized


def test_csat_cache_rejects_duplicate_identity_and_unknown_fields(tmp_path: Path):
    with pytest.raises(CSATCacheError, match="duplicated"):
        CSATCache(
            fetched_weeks=_cache().fetched_weeks,
            fetch_stats=_cache().fetch_stats,
            responses=(
                _response(key="a", rating=103, bucket="positive"),
                _response(key="a", rating=100, bucket="neutral"),
            ),
        )

    destination = tmp_path / "unknown.json"
    destination.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fetched_weeks": {},
                "fetch_stats": {
                    "all_response_count": 0,
                    "included_bot_response_count": 0,
                    "excluded_other_agent_response_count": 0,
                    "excluded_null_agent_response_count": 0,
                },
                "responses": [],
                "agent_id": 73_001,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CSATCacheError, match="invalid"):
        load_csat_cache(destination)


def test_csat_cache_rejects_v1_and_comment_presence_drift(tmp_path: Path):
    destination = tmp_path / "v1.json"
    destination.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fetched_weeks": {},
                "fetch_stats": {
                    "all_response_count": 0,
                    "included_bot_response_count": 0,
                    "excluded_other_agent_response_count": 0,
                    "excluded_null_agent_response_count": 0,
                },
                "responses": [],
            }
        ),
        encoding="utf-8",
    )
    destination.chmod(0o600)

    with pytest.raises(CSATCacheError, match="version"):
        load_csat_cache(destination)
    with pytest.raises(CSATCacheError, match="invalid"):
        CachedCSATResponse(
            response_key=f"sha256:{'c' * 64}",
            ticket_id="123",
            survey_id=43000076179,
            responded_at="2026-07-21T04:15:00Z",
            rating_raw=103,
            satisfaction_bucket="positive",
            comment_present=True,
            comment_redacted=None,
        )


def test_missing_csat_cache_is_available_as_none(tmp_path: Path):
    assert load_csat_cache(tmp_path / "missing.json") is None
