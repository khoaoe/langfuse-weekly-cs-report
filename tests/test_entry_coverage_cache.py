from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

from weekly_cs_report.entry_coverage_cache import (
    EntryCoverageCache,
    EntryCoverageCacheError,
    EntryCoverageRecord,
    load_entry_coverage_cache,
    write_entry_coverage_cache,
)


def _record(
    ticket_id: str = "123",
    opened_at: str = "2026-08-03T01:00:00Z",
    cohort_week: str = "2026-07-27",
    status: str = "not_observed_invoked",
    human_replied: bool | None = False,
) -> EntryCoverageRecord:
    return EntryCoverageRecord(
        ticket_id=ticket_id,
        opened_at=opened_at,
        cohort_week=cohort_week,
        status=status,
        human_replied=human_replied,
    )


def _cache() -> EntryCoverageCache:
    return EntryCoverageCache(
        fetched_weeks={"2026-07-27": "2026-08-04T01:00:00Z"},
        records=(_record(), _record("456", status="invoked_no_result", human_replied=None)),
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
                "status": "not_observed_invoked",
                "human_replied": False,
            }
        ],
    }


def test_entry_cache_round_trips_exact_private_shape(tmp_path: Path):
    destination = tmp_path / "runtime" / "entry_coverage_cache.json"

    write_entry_coverage_cache(destination, _cache())
    loaded = load_entry_coverage_cache(destination)

    assert loaded == _cache()
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert set(payload) == {"schema_version", "fetched_weeks", "records"}
    assert [set(item) for item in payload["records"]] == [
        {"ticket_id", "opened_at", "cohort_week", "status", "human_replied"},
        {"ticket_id", "opened_at", "cohort_week", "status", "human_replied"},
    ]
    serialized = destination.read_text(encoding="utf-8")
    for forbidden in (
        "agent_id",
        "agent_name",
        "author_id",
        "user_id",
        "conversation_id",
        "group_id",
        "body",
        "body_text",
        "attachments",
        "requester",
        "traceId",
        "sessionId",
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
        {"status": "unknown"},
        {"human_replied": 1},
    ],
)
def test_entry_record_rejects_invalid_values(kwargs: dict[str, object]):
    with pytest.raises(EntryCoverageCacheError):
        _record(**kwargs)  # type: ignore[arg-type]


def test_entry_cache_rejects_duplicate_ids_and_schema_drift(tmp_path: Path):
    with pytest.raises(EntryCoverageCacheError, match="duplicate"):
        EntryCoverageCache(
            fetched_weeks={},
            records=(_record(), _record()),
        )

    destination = tmp_path / "cache.json"
    value = _valid_value()
    value["records"][0]["agent_id"] = 123  # type: ignore[index]
    _write_private_json(destination, value)
    with pytest.raises(EntryCoverageCacheError):
        load_entry_coverage_cache(destination)

    value = _valid_value()
    value["schema_version"] = 2
    _write_private_json(destination, value)
    with pytest.raises(EntryCoverageCacheError):
        load_entry_coverage_cache(destination)


def test_entry_cache_rejects_symlink_and_permissive_file(tmp_path: Path):
    missing = tmp_path / "missing.json"
    assert load_entry_coverage_cache(missing) is None

    destination = tmp_path / "cache.json"
    _write_private_json(destination, _valid_value())
    destination.chmod(0o640)
    with pytest.raises(EntryCoverageCacheError):
        load_entry_coverage_cache(destination)

    destination.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(destination)
    with pytest.raises(EntryCoverageCacheError):
        load_entry_coverage_cache(link)
