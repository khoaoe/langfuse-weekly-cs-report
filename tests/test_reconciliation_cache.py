from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import stat

import pytest

from weekly_cs_report import reconciliation_cache as reconciliation_cache_module
from weekly_cs_report.reconciliation_cache import (
    ReconciliationCache,
    ReconciliationCacheError,
    ReconciliationRecord,
    load_reconciliation_cache,
    write_reconciliation_cache,
)


def _record(
    ticket_id: str = "123",
    cohort_week: str = "2026-07-27",
    human_replied_after_ai: bool | None = True,
) -> ReconciliationRecord:
    return ReconciliationRecord(
        ticket_id=ticket_id,
        cohort_week=cohort_week,
        human_replied_after_ai=human_replied_after_ai,
    )


def _cache() -> ReconciliationCache:
    return ReconciliationCache(
        fetched_weeks={
            "2026-07-20": "2026-08-03T01:00:00Z",
            "2026-07-27": "2026-08-03T02:00:00+00:00",
        },
        records=(
            _record(),
            _record(
                ticket_id="456",
                cohort_week="2026-07-20",
                human_replied_after_ai=None,
            ),
        ),
    )


def _write_private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _valid_value() -> dict[str, object]:
    return {
        "schema_version": 1,
        "fetched_weeks": {"2026-07-27": "2026-08-03T02:00:00Z"},
        "records": [
            {
                "ticket_id": "123",
                "cohort_week": "2026-07-27",
                "human_replied_after_ai": False,
            }
        ],
    }


def test_reconciliation_cache_round_trips_exact_private_shape(tmp_path: Path):
    destination = tmp_path / "runtime" / "outcome_reconciliation_cache.json"

    write_reconciliation_cache(destination, _cache())
    loaded = load_reconciliation_cache(destination)

    assert loaded == _cache()
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600

    serialized = destination.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert set(payload) == {"schema_version", "fetched_weeks", "records"}
    assert payload["schema_version"] == 1
    assert [set(record) for record in payload["records"]] == [
        {"ticket_id", "cohort_week", "human_replied_after_ai"},
        {"ticket_id", "cohort_week", "human_replied_after_ai"},
    ]
    assert [record["human_replied_after_ai"] for record in payload["records"]] == [
        True,
        None,
    ]
    for forbidden_field in (
        "agent_id",
        "agent_name",
        "author_id",
        "author_name",
        "user_id",
        "conversation_id",
        "message_id",
        "message_timestamp",
        "created_at",
        "body",
        "body_text",
        "attachments",
        "quoted_text",
    ):
        assert forbidden_field not in serialized


def test_cache_and_records_are_frozen_defensive_copies():
    fetched_weeks = {"2026-07-27": "2026-08-03T02:00:00Z"}
    source_records = [_record()]

    cache = ReconciliationCache(
        fetched_weeks=fetched_weeks,
        records=source_records,  # type: ignore[arg-type]
    )
    fetched_weeks.clear()
    source_records.clear()

    assert dict(cache.fetched_weeks) == {
        "2026-07-27": "2026-08-03T02:00:00Z"
    }
    assert cache.records == (_record(),)
    with pytest.raises(TypeError):
        cache.fetched_weeks["2026-08-04"] = "2026-08-04T00:00:00Z"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        cache.records = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        cache.records[0].ticket_id = "999"  # type: ignore[misc]


@pytest.mark.parametrize(
    "ticket_id",
    ["", "0", "00", "0123", "-1", "+1", "1.0", " 1", "abc", "１２３", 123, True],
)
def test_record_rejects_noncanonical_positive_numeric_ticket_ids(ticket_id: object):
    with pytest.raises(ReconciliationCacheError, match="record is invalid"):
        _record(ticket_id=ticket_id)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "cohort_week",
    ["", "2026-08-02", "2026-08-03T00:00:00Z", "20260803", 20260803],
)
def test_record_rejects_non_monday_iso_cohort_weeks(cohort_week: object):
    with pytest.raises(ReconciliationCacheError, match="cohort week is invalid"):
        _record(cohort_week=cohort_week)  # type: ignore[arg-type]


@pytest.mark.parametrize("result", [0, 1, "true", [], {}])
def test_record_rejects_non_boolean_reconciliation_results(result: object):
    with pytest.raises(ReconciliationCacheError, match="record is invalid"):
        _record(human_replied_after_ai=result)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("week", "fetched_at"),
    [
        ("2026-08-02", "2026-08-03T02:00:00Z"),
        ("20260803", "2026-08-03T02:00:00Z"),
        ("2026-08-03", "2026-08-03T02:00:00"),
        ("2026-08-03", "2026-08-03T09:00:00+07:00"),
        ("2026-08-03", "not-a-timestamp"),
        ("2026-08-03", 123),
    ],
)
def test_cache_rejects_invalid_week_checkpoints(week: object, fetched_at: object):
    with pytest.raises(ReconciliationCacheError):
        ReconciliationCache(
            fetched_weeks={week: fetched_at},  # type: ignore[dict-item]
            records=(),
        )


def test_cache_rejects_duplicate_ticket_ids_even_across_weeks():
    with pytest.raises(ReconciliationCacheError, match="duplicate tickets"):
        ReconciliationCache(
            fetched_weeks={},
            records=(
                _record(ticket_id="123", cohort_week="2026-07-20"),
                _record(ticket_id="123", cohort_week="2026-07-27"),
            ),
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"agent_ids": [1]}),
        lambda value: value.pop("fetched_weeks"),
        lambda value: value.update({"schema_version": 2}),
        lambda value: value.update({"schema_version": True}),
        lambda value: value.update({"records": {}}),
        lambda value: value["records"][0].update({"author_id": 1}),
        lambda value: value["records"][0].pop("cohort_week"),
    ],
)
def test_loader_rejects_schema_drift_and_identity_fields(
    tmp_path: Path,
    mutate,
):
    destination = tmp_path / "cache.json"
    value = _valid_value()
    mutate(value)
    _write_private_json(destination, value)

    with pytest.raises(ReconciliationCacheError):
        load_reconciliation_cache(destination)


def test_loader_rejects_duplicate_records_and_duplicate_json_keys(tmp_path: Path):
    duplicate_records = tmp_path / "duplicate-records.json"
    value = _valid_value()
    value["records"].append(dict(value["records"][0]))
    _write_private_json(duplicate_records, value)
    with pytest.raises(ReconciliationCacheError, match="duplicate tickets"):
        load_reconciliation_cache(duplicate_records)

    duplicate_keys = tmp_path / "duplicate-keys.json"
    duplicate_keys.write_text(
        '{"schema_version":1,"schema_version":1,"fetched_weeks":{},"records":[]}',
        encoding="utf-8",
    )
    duplicate_keys.chmod(0o600)
    with pytest.raises(ReconciliationCacheError, match="invalid"):
        load_reconciliation_cache(duplicate_keys)


def test_loader_requires_an_owner_regular_file_with_mode_0600(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    missing = tmp_path / "missing.json"
    assert load_reconciliation_cache(missing) is None

    destination = tmp_path / "cache.json"
    _write_private_json(destination, _valid_value())
    destination.chmod(0o640)
    with pytest.raises(ReconciliationCacheError, match="invalid"):
        load_reconciliation_cache(destination)

    destination.chmod(0o600)
    directory = tmp_path / "directory"
    directory.mkdir(mode=0o600)
    with pytest.raises(ReconciliationCacheError, match="invalid"):
        load_reconciliation_cache(directory)

    symlink = tmp_path / "cache-link.json"
    symlink.symlink_to(destination)
    with pytest.raises(ReconciliationCacheError, match="invalid"):
        load_reconciliation_cache(symlink)

    effective_uid = os.geteuid()
    monkeypatch.setattr(
        reconciliation_cache_module.os,
        "geteuid",
        lambda: effective_uid + 1,
    )
    with pytest.raises(ReconciliationCacheError, match="invalid"):
        load_reconciliation_cache(destination)


def test_atomic_writer_rejects_nonprivate_or_symlinked_existing_parent(
    tmp_path: Path,
):
    parent = tmp_path / "shared-runtime"
    parent.mkdir(mode=0o750)
    parent.chmod(0o750)
    destination = parent / "outcome_reconciliation_cache.json"

    with pytest.raises(ReconciliationCacheError, match="could not be written"):
        write_reconciliation_cache(destination, _cache())
    assert not destination.exists()

    private_target = tmp_path / "private-target"
    private_target.mkdir(mode=0o700)
    private_target.chmod(0o700)
    linked_parent = tmp_path / "linked-runtime"
    linked_parent.symlink_to(private_target, target_is_directory=True)

    with pytest.raises(ReconciliationCacheError, match="could not be written"):
        write_reconciliation_cache(linked_parent / "cache.json", _cache())
    assert not (private_target / "cache.json").exists()


def test_atomic_writer_forces_new_parent_to_0700_despite_umask(tmp_path: Path):
    destination = tmp_path / "private-runtime" / "cache.json"
    previous_umask = os.umask(0o777)
    try:
        write_reconciliation_cache(destination, _cache())
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_writer_rejects_a_non_directory_parent(tmp_path: Path):
    parent = tmp_path / "not-a-directory"
    parent.write_text("sentinel", encoding="utf-8")

    with pytest.raises(ReconciliationCacheError, match="could not be written"):
        write_reconciliation_cache(parent / "cache.json", _cache())

    assert parent.read_text(encoding="utf-8") == "sentinel"
