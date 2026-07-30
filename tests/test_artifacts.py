from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone

import pytest

from weekly_cs_report.artifacts import ArtifactSafetyError, ProtectedArtifactStore


def test_protected_store_enforces_permissions_latest_copy_and_thirty_run_retention(
    tmp_path,
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for offset in range(31):
        run = store.start_run(first + timedelta(days=offset))
        run.write_json("summary.json", {"run": offset})
        run.publish_latest()

    run_directories = sorted(
        path for path in store.root.iterdir() if path.name.startswith("run-")
    )
    latest_dir = store.root / "latest"
    report_file = latest_dir / "summary.json"

    assert len(run_directories) == 30
    assert not (store.root / "run-20260101T000000000000Z").exists()
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(latest_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(report_file.stat().st_mode) == 0o600
    assert json.loads(report_file.read_text()) == {"run": 30}


@pytest.mark.parametrize(
    "payload",
    [
        {"input": "raw"},
        {"safe": [{"output": "raw"}]},
        {"safe": {"comments": []}},
        {"user_input": "raw"},
        {"user_id": "raw"},
        {"trans_id": "raw"},
        {"response": "raw"},
    ],
)
def test_protected_store_rejects_forbidden_keys_before_serialization(
    tmp_path, payload
):
    run = ProtectedArtifactStore(tmp_path / "artifacts").start_run(
        datetime(2026, 7, 29, tzinfo=timezone.utc)
    )

    with pytest.raises(ArtifactSafetyError):
        run.write_json("summary.json", payload)

    assert not (run.path / "summary.json").exists()


def test_protected_store_rejects_unapproved_names_and_csv_columns(tmp_path):
    run = ProtectedArtifactStore(tmp_path / "artifacts").start_run(
        datetime(2026, 7, 29, tzinfo=timezone.utc)
    )

    with pytest.raises(ArtifactSafetyError):
        run.write_json("../escape.json", {"safe": True})
    with pytest.raises(ArtifactSafetyError):
        run.write_csv("investigation.csv", [{"session_id": "1", "response": "raw"}])

    assert not (tmp_path / "escape.json").exists()

