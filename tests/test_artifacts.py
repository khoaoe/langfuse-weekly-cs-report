from __future__ import annotations

import csv
import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from weekly_cs_report import artifacts
from weekly_cs_report.artifacts import ArtifactSafetyError, ProtectedArtifactStore


def _run(store: ProtectedArtifactStore):
    return store.start_run(datetime(2026, 7, 29, tzinfo=timezone.utc))


def _assert_unchanged(path, contents: str, mode: int) -> None:
    assert path.read_text() == contents
    assert stat.S_IMODE(path.stat().st_mode) == mode


def _file_snapshot(directory):
    return {
        path.relative_to(directory): (
            path.read_bytes(),
            stat.S_IMODE(path.stat().st_mode),
        )
        for path in directory.rglob("*")
        if path.is_file()
    }


def _assert_no_latest_transaction_residue(root) -> None:
    assert not list(root.glob(".latest-staging-*"))
    assert not list(root.glob(".latest-backup-*"))


@pytest.mark.parametrize("broken", [False, True])
def test_protected_store_rejects_root_symlinks_without_changing_targets(
    tmp_path, broken
):
    target = tmp_path / "external-root"
    target.mkdir()
    target.chmod(0o750)
    sentinel = target / "untouched.txt"
    sentinel.write_text("keep")
    sentinel.chmod(0o640)
    root = tmp_path / "artifacts"
    root.symlink_to(tmp_path / "missing-root" if broken else target, target_is_directory=True)

    with pytest.raises(ArtifactSafetyError, match="symlink"):
        ProtectedArtifactStore(root)

    assert root.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o750
    _assert_unchanged(sentinel, "keep", 0o640)


@pytest.mark.parametrize("broken", [False, True])
def test_protected_store_rejects_symlinked_root_path_components(tmp_path, broken):
    external_parent = tmp_path / "external-parent"
    external_parent.mkdir()
    external_parent.chmod(0o750)
    sentinel = external_parent / "untouched.txt"
    sentinel.write_text("keep")
    sentinel.chmod(0o640)
    component = tmp_path / "component"
    component.symlink_to(
        tmp_path / "missing-component" if broken else external_parent,
        target_is_directory=True,
    )

    with pytest.raises(ArtifactSafetyError, match="symlink"):
        ProtectedArtifactStore(component / "artifacts")

    assert component.is_symlink()
    assert not (external_parent / "artifacts").exists()
    assert stat.S_IMODE(external_parent.stat().st_mode) == 0o750
    _assert_unchanged(sentinel, "keep", 0o640)


@pytest.mark.parametrize("broken", [False, True])
def test_start_run_rejects_run_directory_symlinks_without_changing_targets(
    tmp_path, broken
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    as_of = datetime(2026, 7, 29, tzinfo=timezone.utc)
    run_path = store.root / "run-20260729T000000000000Z"
    target = tmp_path / "external-run"
    target.mkdir()
    target.chmod(0o750)
    sentinel = target / "untouched.txt"
    sentinel.write_text("keep")
    sentinel.chmod(0o640)
    run_path.symlink_to(tmp_path / "missing-run" if broken else target, target_is_directory=True)

    with pytest.raises(ArtifactSafetyError, match="symlink"):
        store.start_run(as_of)

    assert run_path.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o750
    _assert_unchanged(sentinel, "keep", 0o640)


@pytest.mark.parametrize("broken", [False, True])
def test_publish_latest_rejects_symlinks_without_changing_targets(tmp_path, broken):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    run = _run(store)
    run.write_json("summary.json", {"safe": True})
    target = tmp_path / "external-latest"
    target.mkdir()
    target.chmod(0o750)
    sentinel = target / "untouched.txt"
    sentinel.write_text("keep")
    sentinel.chmod(0o640)
    latest = store.root / "latest"
    latest.symlink_to(tmp_path / "missing-latest" if broken else target, target_is_directory=True)

    with pytest.raises(ArtifactSafetyError, match="symlink"):
        run.publish_latest()

    assert latest.is_symlink()
    assert stat.S_IMODE(target.stat().st_mode) == 0o750
    _assert_unchanged(sentinel, "keep", 0o640)


@pytest.mark.parametrize(
    ("name", "write"),
    [
        ("summary.json", lambda run: run.write_json("summary.json", {"safe": True})),
        (
            "summary.csv",
            lambda run: run.write_csv("summary.csv", [{"safe": "true"}]),
        ),
    ],
)
@pytest.mark.parametrize("broken", [False, True])
def test_writes_reject_final_destination_symlinks_without_changing_targets(
    tmp_path, name, write, broken
):
    run = _run(ProtectedArtifactStore(tmp_path / "artifacts"))
    target = tmp_path / f"external-{name}"
    target.write_text("keep")
    target.chmod(0o640)
    destination = run.path / name
    destination.symlink_to(tmp_path / f"missing-{name}" if broken else target)

    with pytest.raises(ArtifactSafetyError, match="symlink"):
        write(run)

    assert destination.is_symlink()
    _assert_unchanged(target, "keep", 0o640)


@pytest.mark.parametrize("broken", [False, True])
def test_write_rejects_symlinked_store_root_path_components(tmp_path, broken):
    container = tmp_path / "container"
    store = ProtectedArtifactStore(container / "artifacts")
    run = _run(store)
    destination = run.write_json("summary.json", {"version": "old"})
    previous = destination.read_bytes()
    external_parent = tmp_path / "external-parent"
    container.rename(external_parent)
    component_target = tmp_path / "missing-component" if broken else external_parent
    container.symlink_to(component_target, target_is_directory=True)
    external_destination = (
        external_parent / "artifacts" / run.path.name / destination.name
    )
    external_mode = stat.S_IMODE(external_parent.stat().st_mode)

    with pytest.raises(ArtifactSafetyError, match="symlink"):
        run.write_json("summary.json", {"version": "new"})

    assert container.is_symlink()
    assert external_destination.read_bytes() == previous
    assert stat.S_IMODE(external_parent.stat().st_mode) == external_mode


@pytest.mark.parametrize("broken", [False, True])
def test_publish_latest_rejects_symlinked_store_root_path_components(tmp_path, broken):
    container = tmp_path / "container"
    store = ProtectedArtifactStore(container / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    external_parent = tmp_path / "external-parent"
    container.rename(external_parent)
    component_target = tmp_path / "missing-component" if broken else external_parent
    container.symlink_to(component_target, target_is_directory=True)
    latest = external_parent / "artifacts" / "latest"
    previous = _file_snapshot(latest)
    external_mode = stat.S_IMODE(external_parent.stat().st_mode)

    with pytest.raises(ArtifactSafetyError, match="symlink"):
        new_run.publish_latest()

    assert container.is_symlink()
    assert _file_snapshot(latest) == previous
    assert stat.S_IMODE(external_parent.stat().st_mode) == external_mode


def test_json_serialization_failure_preserves_previous_artifact_and_cleans_temp(
    tmp_path, monkeypatch
):
    run = _run(ProtectedArtifactStore(tmp_path / "artifacts"))
    destination = run.write_json("summary.json", {"previous": True})
    previous = destination.read_bytes()

    def fail_dumps(*args, **kwargs):
        raise TypeError("serialization failed")

    monkeypatch.setattr(artifacts.json, "dumps", fail_dumps)

    with pytest.raises(TypeError, match="serialization failed"):
        run.write_json("summary.json", {"replacement": True})

    assert destination.read_bytes() == previous
    assert not list(run.path.glob(".*.tmp"))


def test_csv_serialization_failure_preserves_previous_artifact_and_cleans_temp(tmp_path):
    class UnserializableCell:
        def __str__(self) -> str:
            raise TypeError("serialization failed")

    run = _run(ProtectedArtifactStore(tmp_path / "artifacts"))
    destination = run.write_csv("summary.csv", [{"value": "previous"}])
    previous = destination.read_bytes()

    with pytest.raises(TypeError, match="serialization failed"):
        run.write_csv("summary.csv", [{"value": UnserializableCell()}])

    assert destination.read_bytes() == previous
    assert not list(run.path.glob(".*.tmp"))


@pytest.mark.parametrize(
    ("seed", "write"),
    [
        (
            lambda run: run.write_json("summary.json", {"previous": True}),
            lambda run: run.write_json("summary.json", {"replacement": True}),
        ),
        (
            lambda run: run.write_csv("summary.csv", [{"value": "previous"}]),
            lambda run: run.write_csv("summary.csv", [{"value": "replacement"}]),
        ),
    ],
)
def test_replace_failure_preserves_previous_artifact_and_cleans_temp(
    tmp_path, monkeypatch, seed, write
):
    run = _run(ProtectedArtifactStore(tmp_path / "artifacts"))
    destination = seed(run)
    previous = destination.read_bytes()

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr(artifacts.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write(run)

    assert destination.read_bytes() == previous
    assert not list(run.path.glob(".*.tmp"))


def test_replace_that_completes_before_raising_does_not_claim_previous_artifact(
    tmp_path, monkeypatch
):
    run = _run(ProtectedArtifactStore(tmp_path / "artifacts"))
    destination = run.write_json("summary.json", {"version": "old"})
    real_replace = artifacts.os.replace

    def replace_then_raise(source, target):
        real_replace(source, target)
        raise OSError("replace reported failure after completion")

    monkeypatch.setattr(artifacts.os, "replace", replace_then_raise)

    with pytest.raises(OSError, match="reported failure"):
        run.write_json("summary.json", {"version": "new"})

    assert json.loads(destination.read_text()) == {"version": "new"}
    assert not list(run.path.glob(".*.tmp"))


def test_publish_latest_copy_failure_preserves_existing_latest_and_cleans_staging(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})

    def fail_copy(source, destination, *args, **kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(artifacts.shutil, "copyfile", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        new_run.publish_latest()

    assert _file_snapshot(latest) == previous
    _assert_no_latest_transaction_residue(store.root)


def test_publish_latest_final_swap_failure_restores_existing_latest_and_cleans_staging(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    real_replace = artifacts.os.replace

    def fail_final_swap(source, destination):
        if Path(source).name.startswith(".latest-staging-") and Path(destination) == latest:
            raise OSError("final swap failed")
        return real_replace(source, destination)

    monkeypatch.setattr(artifacts.os, "replace", fail_final_swap)

    with pytest.raises(OSError, match="final swap failed"):
        new_run.publish_latest()

    assert _file_snapshot(latest) == previous
    _assert_no_latest_transaction_residue(store.root)


def test_backup_cleanup_failure_after_commit_keeps_new_latest_and_returns_success(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    real_rmtree = artifacts.shutil.rmtree

    def fail_backup_cleanup(directory, *args, **kwargs):
        if Path(directory).name.startswith(".latest-backup-"):
            raise OSError("backup cleanup failed")
        return real_rmtree(directory, *args, **kwargs)

    monkeypatch.setattr(artifacts.shutil, "rmtree", fail_backup_cleanup)

    assert new_run.publish_latest() == latest
    assert json.loads((latest / "summary.json").read_text()) == {"version": "new"}
    assert not list(store.root.glob(".latest-staging-*"))
    backups = list(store.root.glob(".latest-backup-*"))
    assert len(backups) == 1
    assert _file_snapshot(backups[0]) == previous


def test_successful_final_swap_reaches_commit_point_and_cleans_backup(tmp_path):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})

    new_run.publish_latest()

    assert json.loads((store.root / "latest" / "summary.json").read_text()) == {
        "version": "new"
    }
    _assert_no_latest_transaction_residue(store.root)


def test_staging_cleanup_failure_does_not_mask_original_copy_failure(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    real_rmtree = artifacts.shutil.rmtree

    def fail_copy(source, destination, *args, **kwargs):
        raise OSError("copy failed")

    def fail_staging_cleanup(directory, *args, **kwargs):
        if Path(directory).name.startswith(".latest-staging-"):
            raise OSError("staging cleanup failed")
        return real_rmtree(directory, *args, **kwargs)

    monkeypatch.setattr(artifacts.shutil, "copyfile", fail_copy)
    monkeypatch.setattr(artifacts.shutil, "rmtree", fail_staging_cleanup)

    with pytest.raises(OSError, match="copy failed"):
        new_run.publish_latest()

    assert _file_snapshot(latest) == previous
    assert len(list(store.root.glob(".latest-staging-*"))) == 1
    assert not list(store.root.glob(".latest-backup-*"))


def test_staging_cleanup_failure_does_not_mask_original_swap_failure(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    real_replace = artifacts.os.replace
    real_rmtree = artifacts.shutil.rmtree

    def fail_final_swap(source, destination):
        if Path(source).name.startswith(".latest-staging-") and Path(destination) == latest:
            raise OSError("final swap failed")
        return real_replace(source, destination)

    def fail_staging_cleanup(directory, *args, **kwargs):
        if Path(directory).name.startswith(".latest-staging-"):
            raise OSError("staging cleanup failed")
        return real_rmtree(directory, *args, **kwargs)

    monkeypatch.setattr(artifacts.os, "replace", fail_final_swap)
    monkeypatch.setattr(artifacts.shutil, "rmtree", fail_staging_cleanup)

    with pytest.raises(OSError, match="final swap failed"):
        new_run.publish_latest()

    assert _file_snapshot(latest) == previous
    assert len(list(store.root.glob(".latest-staging-*"))) == 1
    assert not list(store.root.glob(".latest-backup-*"))


def test_first_latest_move_that_completes_then_raises_restores_old_latest(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    real_replace = artifacts.os.replace

    def first_move_then_raise(source, destination):
        if Path(source) == latest and Path(destination).name.startswith(".latest-backup-"):
            real_replace(source, destination)
            raise OSError("first move reported failure after completion")
        return real_replace(source, destination)

    monkeypatch.setattr(artifacts.os, "replace", first_move_then_raise)

    with pytest.raises(OSError, match="first move reported failure"):
        new_run.publish_latest()

    assert _file_snapshot(latest) == previous
    _assert_no_latest_transaction_residue(store.root)


def test_rollback_move_that_completes_then_raises_keeps_original_error_and_old_latest(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    real_replace = artifacts.os.replace

    def first_and_rollback_move_then_raise(source, destination):
        if Path(source) == latest and Path(destination).name.startswith(".latest-backup-"):
            real_replace(source, destination)
            raise OSError("first move reported failure after completion")
        if Path(source).name.startswith(".latest-backup-") and Path(destination) == latest:
            real_replace(source, destination)
            raise OSError("rollback reported failure after completion")
        return real_replace(source, destination)

    monkeypatch.setattr(artifacts.os, "replace", first_and_rollback_move_then_raise)

    with pytest.raises(OSError, match="first move reported failure"):
        new_run.publish_latest()

    assert _file_snapshot(latest) == previous
    _assert_no_latest_transaction_residue(store.root)


def test_final_swap_that_completes_then_raises_keeps_new_latest_and_old_backup(
    tmp_path, monkeypatch
):
    store = ProtectedArtifactStore(tmp_path / "artifacts")
    old_run = _run(store)
    old_run.write_json("summary.json", {"version": "old"})
    old_run.publish_latest()
    latest = store.root / "latest"
    previous = _file_snapshot(latest)
    new_run = store.start_run(datetime(2026, 7, 30, tzinfo=timezone.utc))
    new_run.write_json("summary.json", {"version": "new"})
    real_replace = artifacts.os.replace

    def final_move_then_raise(source, destination):
        if Path(source).name.startswith(".latest-staging-") and Path(destination) == latest:
            real_replace(source, destination)
            raise OSError("final move reported failure after completion")
        return real_replace(source, destination)

    monkeypatch.setattr(artifacts.os, "replace", final_move_then_raise)

    with pytest.raises(OSError, match="final move reported failure"):
        new_run.publish_latest()

    assert json.loads((latest / "summary.json").read_text()) == {"version": "new"}
    backups = list(store.root.glob(".latest-backup-*"))
    assert len(backups) == 1
    assert _file_snapshot(backups[0]) == previous
    assert not list(store.root.glob(".latest-staging-*"))


def test_successful_json_and_csv_commits_are_private_and_round_trip_exactly(tmp_path):
    run = _run(ProtectedArtifactStore(tmp_path / "artifacts"))
    payload = {
        "as_of": datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc),
        "nested": {"count": 2},
    }
    rows = [
        {"bucket": "billing", "count": "2"},
        {"bucket": "topup", "count": "3"},
    ]

    json_path = run.write_json("summary.json", payload)
    csv_path = run.write_csv("summary.csv", rows, fieldnames=("bucket", "count"))

    assert stat.S_IMODE(json_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(csv_path.stat().st_mode) == 0o600
    assert json.loads(json_path.read_text()) == {
        "as_of": "2026-07-29T10:30:00Z",
        "nested": {"count": 2},
    }
    with csv_path.open(newline="") as file:
        assert list(csv.DictReader(file)) == rows


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
