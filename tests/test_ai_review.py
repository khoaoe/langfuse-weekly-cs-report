from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from weekly_cs_report.ai_review import (
    AIReviewError,
    AIReviewLabelConfig,
    AIReviewRecord,
    build_ai_review_record,
    load_ai_review_label_config,
    parse_reopen_status,
    parse_user_replied,
)
from weekly_cs_report.ai_review_cache import (
    AIReviewCache,
    AIReviewCacheError,
    load_ai_review_cache,
    write_ai_review_cache,
)
from weekly_cs_report.freshdesk_csat import FreshdeskClient, FreshdeskSettings, FreshdeskUIClient
from weekly_cs_report.freshdesk_entry_coverage import FreshdeskTicketMetadata


# --- HTTP-transport seam: both auth paths agree on the 5 AI-review fields --


def _rest_transport(rows: list[dict]) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    return httpx.MockTransport(handler)


def _ui_transport(rows: list[dict]) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tickets": rows})

    return httpx.MockTransport(handler)


_ROW = {
    "id": 123,
    "created_at": "2026-08-24T01:00:00Z",
    "custom_fields": {
        "cf_rating_ai": "Hài Lòng",
        "cf_s_ln_hu_kim_ai": "0",
        "cf_ngy_hu_kim_ai": "2026-08-25",
        "cf_trng_thi_ai_reopen": "Chưa phản hồi Private Note",
        "cf_trng_thi_phn_hi_ai_cho_user": "Đã trả lời cho User",
    },
}
_EXPECTED = FreshdeskTicketMetadata(
    ticket_id="123",
    created_at="2026-08-24T01:00:00Z",
    ai_review_rating_raw="Hài Lòng",
    ai_review_count_raw="0",
    ai_review_date_raw="2026-08-25",
    ai_reopen_status_raw="Chưa phản hồi Private Note",
    ai_user_replied_raw="Đã trả lời cho User",
)


def test_rest_client_extracts_ai_review_fields_including_zero_count():
    with FreshdeskClient(
        FreshdeskSettings("https://vngzalopay.freshdesk.com", "secret"),
        transport=_rest_transport([_ROW]),
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 8, 23, tzinfo=timezone.utc)
        )
    assert result == (_EXPECTED,)
    assert result[0].ai_review_count_raw == "0"


def test_ui_client_extracts_same_ai_review_fields_as_rest():
    with FreshdeskUIClient(
        "cs_session=abc123", transport=_ui_transport([_ROW])
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 8, 23, tzinfo=timezone.utc)
        )
    assert result == (_EXPECTED,)


def test_both_clients_treat_missing_custom_fields_as_all_none():
    row = {"id": 124, "created_at": "2026-08-24T01:00:00Z"}
    with FreshdeskClient(
        FreshdeskSettings("https://vngzalopay.freshdesk.com", "secret"),
        transport=_rest_transport([row]),
    ) as client:
        result = client.list_ticket_metadata(
            updated_since=datetime(2026, 8, 23, tzinfo=timezone.utc)
        )
    assert result[0].ai_review_rating_raw is None
    assert result[0].ai_reopen_status_raw is None


# --- parse_reopen_status: the 3 real raw values, plus fail-closed on junk --


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Chưa phản hồi Private Note", (False, None)),
        ("Đã phản hồi Private Note", (True, None)),
        ("Đã phản hồi 1", (True, 1)),
        ("Đã phản hồi 20", (True, 20)),
    ],
)
def test_parse_reopen_status_handles_all_three_raw_shapes(raw, expected):
    assert parse_reopen_status(raw) == expected


@pytest.mark.parametrize("raw", ["Đã phản hồi 21", "Đã phản hồi 0", "unknown", ""])
def test_parse_reopen_status_fails_closed_on_unapproved_value(raw):
    with pytest.raises(AIReviewError):
        parse_reopen_status(raw)


def test_parse_user_replied_fails_closed_on_unapproved_value():
    assert parse_user_replied("Đã trả lời cho User") is True
    assert parse_user_replied("Chưa trả lời cho User") is False
    with pytest.raises(AIReviewError):
        parse_user_replied("khong ro")


# --- build_ai_review_record: fail-closed on an unapproved rating label ------


def test_build_ai_review_record_fails_closed_on_unapproved_rating():
    labels = AIReviewLabelConfig(rating_labels={"Hài Lòng": "satisfied"})
    ticket = FreshdeskTicketMetadata(
        ticket_id="1",
        created_at="2026-08-24T01:00:00Z",
        ai_review_rating_raw="Không rõ",
    )
    with pytest.raises(AIReviewError):
        build_ai_review_record(ticket, labels)


def test_build_ai_review_record_leaves_unrated_tickets_none():
    labels = AIReviewLabelConfig(rating_labels={"Hài Lòng": "satisfied"})
    ticket = FreshdeskTicketMetadata(ticket_id="1", created_at="2026-08-24T01:00:00Z")
    record = build_ai_review_record(ticket, labels)
    assert record.rating is None
    assert record.reopen_replied is None
    assert record.user_replied is None


# --- load_ai_review_label_config: the approval contract ---------------------


def test_load_ai_review_label_config_reads_the_real_approved_file():
    config = load_ai_review_label_config(
        Path(__file__).resolve().parent.parent / "config" / "ai_review_labels.v1.json"
    )
    assert config.slug_for("Hài Lòng") == "satisfied"
    assert config.slug_for("Hài lòng có chỉnh sửa") == "satisfied_with_edit"
    assert config.slug_for("Cần chỉnh sửa") == "needs_edit"
    with pytest.raises(AIReviewError):
        config.slug_for("Không rõ")


def test_load_ai_review_label_config_rejects_missing_approval(tmp_path: Path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "approved_by": "not-po",
                "approved_at": "2026-09-04",
                "notes": "x",
                "rating_labels": {"a": "satisfied"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AIReviewError):
        load_ai_review_label_config(path)


# --- AIReviewCache: round trip and fail-closed corruption handling ---------


def _sample_record() -> AIReviewRecord:
    return AIReviewRecord(
        ticket_id="123",
        opened_at="2026-08-24T01:00:00Z",
        cohort_week="2026-08-24",
        rating="satisfied",
        review_count=0,
        review_date="2026-08-25",
        reopen_replied=True,
        reopen_reply_count=3,
        user_replied=True,
    )


def test_ai_review_cache_round_trips(tmp_path: Path):
    cache = AIReviewCache(
        fetched_weeks={"2026-08-24": "2026-09-05T00:00:00Z"},
        records=(_sample_record(),),
    )
    path = tmp_path / "ai_review_cache.json"
    write_ai_review_cache(path, cache)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = load_ai_review_cache(path)
    assert loaded == cache


def test_ai_review_cache_rejects_duplicate_json_keys(tmp_path: Path):
    path = tmp_path / "ai_review_cache.json"
    path.write_text('{"schema_version": 1, "schema_version": 2}', encoding="utf-8")
    os.chmod(path, 0o600)
    with pytest.raises(AIReviewCacheError):
        load_ai_review_cache(path)


def test_ai_review_cache_rejects_world_readable_file(tmp_path: Path):
    cache = AIReviewCache(fetched_weeks={}, records=())
    path = tmp_path / "ai_review_cache.json"
    write_ai_review_cache(path, cache)
    os.chmod(path, 0o644)
    with pytest.raises(AIReviewCacheError):
        load_ai_review_cache(path)


def test_ai_review_cache_missing_file_returns_none(tmp_path: Path):
    assert load_ai_review_cache(tmp_path / "missing.json") is None


def test_parse_reopen_status_accepts_bare_replied() -> None:
    # Freshdesk emits this variant live; it must mean replied, count unknown.
    assert parse_reopen_status("Đã phản hồi") == (True, None)
