from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

from weekly_cs_report.ai_tag_cache import (
    AiTagCache,
    AiTagCacheError,
    AiTagRecord,
    load_ai_tag_cache,
    write_ai_tag_cache,
)


def _record(
    ticket_id: str = "123",
    opened_at: str = "2026-08-03T01:00:00Z",
    cohort_week: str = "2026-07-27",
) -> AiTagRecord:
    return AiTagRecord(ticket_id=ticket_id, opened_at=opened_at, cohort_week=cohort_week)


def _cache() -> AiTagCache:
    return AiTagCache(
        fetched_weeks={"2026-07-27": "2026-08-04T01:00:00Z"},
        records=(_record(), _record("456")),
    )


def _write_private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _valid_value() -> dict[str, object]:
    return {
        "schema_version": 1,
        "fetched_weeks": {"2026-07-27": "2026-08-04T01:00:00Z"},
        "records": [
            {
                "ticket_id": "123",
                "opened_at": "2026-08-03T01:00:00Z",
                "cohort_week": "2026-07-27",
            }
        ],
    }


def test_ai_tag_record_rejects_ticket_id_over_twenty_digits():
    with pytest.raises(AiTagCacheError):
        _record(ticket_id="1" * 21)


def test_ai_tag_cache_round_trips_exact_private_shape(tmp_path: Path):
    destination = tmp_path / "runtime" / "ai_tag_cache.json"

    write_ai_tag_cache(destination, _cache())
    loaded = load_ai_tag_cache(destination)

    assert loaded == _cache()
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "fetched_weeks", "records"}
    assert [set(item) for item in payload["records"]] == [
        {"ticket_id", "opened_at", "cohort_week"},
        {"ticket_id", "opened_at", "cohort_week"},
    ]
    serialized = destination.read_text(encoding="utf-8")
    for forbidden in (
        "subject",
        "requester",
        "email",
        "phone",
        "body",
        "body_text",
        "tags",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ticket_id": "0"},
        {"ticket_id": "01"},
        {"ticket_id": "abc"},
        {"opened_at": "2026-08-03T01:00:00+07:00"},
        {"opened_at": "2026-08-03T01:00:00"},
        {"cohort_week": "2026-08-02"},
    ],
)
def test_ai_tag_record_rejects_invalid_values(kwargs: dict[str, object]):
    with pytest.raises(AiTagCacheError):
        _record(**kwargs)  # type: ignore[arg-type]


def test_ai_tag_cache_rejects_duplicate_ids_and_schema_drift(tmp_path: Path):
    with pytest.raises(AiTagCacheError, match="duplicate"):
        AiTagCache(fetched_weeks={}, records=(_record(), _record()))

    destination = tmp_path / "cache.json"
    value = _valid_value()
    value["records"][0]["subject"] = "leak"  # type: ignore[index]
    _write_private_json(destination, value)
    with pytest.raises(AiTagCacheError):
        load_ai_tag_cache(destination)

    value = _valid_value()
    value["schema_version"] = 2
    _write_private_json(destination, value)
    with pytest.raises(AiTagCacheError):
        load_ai_tag_cache(destination)


def test_ai_tag_cache_rejects_symlink_and_permissive_file(tmp_path: Path):
    missing = tmp_path / "missing.json"
    assert load_ai_tag_cache(missing) is None

    destination = tmp_path / "cache.json"
    _write_private_json(destination, _valid_value())
    destination.chmod(0o640)
    with pytest.raises(AiTagCacheError):
        load_ai_tag_cache(destination)

    destination.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(destination)
    with pytest.raises(AiTagCacheError):
        load_ai_tag_cache(link)
