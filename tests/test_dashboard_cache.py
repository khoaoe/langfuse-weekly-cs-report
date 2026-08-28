from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import threading

import pytest

from weekly_cs_report import dashboard_cache
from weekly_cs_report.dashboard_cache import (
    ProtectedSnapshotStore,
    SnapshotManager,
)
from weekly_cs_report.dashboard_schema import DashboardSnapshot
from weekly_cs_report.langfuse_client import (
    LangfuseAPIError,
    LangfuseRequestCancelled,
)
from weekly_cs_report.models import InvariantError


NOW = datetime(2026, 7, 29, 5, tzinfo=timezone.utc)


def _empty_transfer_reasons() -> dict[str, object]:
    return {
        "observed_transfer_denominator": 0,
        "triggers": [],
        "tpe": [],
        "step_result_missing": {"count": 0, "denominator": 0},
        "guardrail": [],
        "escalation_guard_blocked": {"count": 0, "denominator": 0},
    }


class FakeClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


class FailOnCallClock:
    def __init__(self, value: datetime, *, fail_call: int, error: Exception) -> None:
        self.value = value
        self.fail_call = fail_call
        self.error = error
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        if self.calls == self.fail_call:
            raise self.error
        return self.value


def _snapshot(generated_at: datetime) -> DashboardSnapshot:
    generated_at_text = generated_at.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return DashboardSnapshot(
        generated_at=generated_at,
        dashboard={
            "generated_at": generated_at_text,
            "source": {
                "traces_fetched": 0,
                "traces_deduplicated": 0,
                "observations_fetched": 0,
            },
            "enrichment_status": "partial",
            "data_range": {"first_week_with_data": None, "weeks_without_data": []},
            "views": {
                view: {
                    "totals": {"eligible_ticket_count": 0, "transfer_total": 0, "gt4_turn_total": 0, "weekend_start_count": 0},
                    "outcomes": {"ai_end_to_end": 0, "ai_then_cs": 0, "direct_cs": 0, "unclassified": 0},
                    "ai_first": {"count": 0, "rate": 0.0},
                    "reopen": {"lifetime": {"numerator": 0, "denominator": 0}, "within_7d": {"numerator": 0, "denominator": 0}},
                    "weekly": [],
                    "segments": {name: {("Chưa ghi nhận" if name == "skill" else "Không xác định"): {"total": 0, "ai_first": 0, "transferred": 0, "reopen": 0}} for name in ("issue_category", "app", "product_code", "skill", "intent", "tpe", "guardrail_rule", "entry_point", "model_core")},
                    "transfer_reasons": _empty_transfer_reasons(),
                    "by_week": {},
                    "same_period": None,
                    "csat": None,
                    "outcome_reconciliation": None,
                    "entry_coverage": None,
                    "rule_gt4": {"gt4_turn_total": 0, "gt4_turn_with_cs": 0, "gt4_turn_without_cs": 0, "max_replies_rule_fired": 0},
                }
                for view in ("mon_sun", "mon_fri")
            },
            "coverage": {"issue_category": 0.0, "app": 0.0, "tpe": 0.0, "intent": 0.0, "skill": 0.0},
            "unmapped_tpe_codes": [],
            "gate_status": {"allowed": True, "structural_invalid_rate": 0.0, "reasons": []},
            "data_quality": {"counts": {}, "weekend_start_count": 0, "left_censored_count": 0, "pre_window_start_count": 0, "invalid_keyed_session_count": 0, "unkeyed_trace_count": 0},
        },
        tickets=(),
    )


def test_storage_ignores_legacy_v2_without_attempting_a_metric_conversion(tmp_path: Path, caplog):
    snapshot = _snapshot(NOW)
    stored = snapshot.storage_dict()
    legacy = json.loads(json.dumps(stored))
    legacy["schema_version"] = 2

    directory = tmp_path / "runtime"
    directory.mkdir(mode=0o700)
    (directory / "dashboard_snapshot.json").write_text(json.dumps(legacy), encoding="utf-8")
    restored = ProtectedSnapshotStore(directory).load()

    assert restored is None
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "weekly_cs_report.runtime"
    ]
    assert events == [{"event": "snapshot_load_ignored", "code": "invalid_snapshot"}]


def test_strict_store_rejects_incomplete_enrichment_without_overwriting_snapshot(
    tmp_path: Path,
):
    directory = tmp_path / "runtime"
    regular_store = ProtectedSnapshotStore(directory)
    partial = _snapshot(NOW)
    regular_store.save(partial)

    strict_store = ProtectedSnapshotStore(
        directory,
        require_complete_enrichment=True,
    )
    assert strict_store.load() is None
    with pytest.raises(InvariantError, match="enrichment is incomplete"):
        strict_store.save(partial)

    assert regular_store.load() == partial


@contextmanager
def _manager(
    loader,
    store: ProtectedSnapshotStore,
    clock: FakeClock,
):
    manager = SnapshotManager(loader, store, clock=clock)
    try:
        yield manager
    finally:
        manager.close()


def test_peek_returns_current_view_without_starting_loader(tmp_path: Path):
    """Using the refreshing read path for health probes can trigger upstream work."""
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("load")
        return _snapshot(NOW)

    with _manager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        FakeClock(NOW),
    ) as manager:
        view = manager.peek()

        assert view.snapshot is None
        assert view.refreshing is False
        assert view.last_error_code is None
        assert view.last_error_at is None
        assert calls == []


def test_first_get_starts_one_blocking_load_and_transitions_to_ready(tmp_path: Path):
    """Running the loader inline or submitting it twice breaks non-blocking startup."""
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    expected = _snapshot(NOW)

    def loader() -> DashboardSnapshot:
        calls.append("load")
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return expected

    clock = FakeClock(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    with _manager(loader, store, clock) as manager:
        view = manager.get()

        assert view.status == "loading"
        assert view.snapshot is None
        assert view.refreshing is True
        assert started.wait(2)
        assert calls == ["load"]

        release.set()
        assert manager.wait_for_idle(2) is True
        ready = manager.get()

        assert ready.status == "ready"
        assert ready.snapshot == expected
        assert ready.refreshing is False
        assert ready.last_error_code is None
        assert ready.last_error_at is None
        assert calls == ["load"]


def test_repeated_get_inside_default_300_second_ttl_does_not_reload(tmp_path: Path):
    """Using a TTL shorter than 300 seconds causes unnecessary upstream reads."""
    calls: list[datetime] = []
    clock = FakeClock(NOW)

    def loader() -> DashboardSnapshot:
        calls.append(clock())
        return _snapshot(clock())

    with _manager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock,
    ) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True

        clock.advance(timedelta(seconds=299))
        views = [manager.get() for _ in range(10)]

        assert all(view.status == "ready" for view in views)
        assert len(calls) == 1


def test_long_refresh_ttl_starts_at_successful_commit(tmp_path: Path):
    """Using report generated_at makes a slow refresh stale as soon as it commits."""
    clock = FakeClock(NOW)
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_release = threading.Event()
    calls: list[int] = []
    expected = _snapshot(NOW)

    def loader() -> DashboardSnapshot:
        call_number = len(calls) + 1
        calls.append(call_number)
        if call_number == 1:
            first_started.set()
            if not first_release.wait(5):
                raise TimeoutError("test did not release first loader")
        else:
            second_started.set()
            if not second_release.wait(5):
                raise TimeoutError("test did not release second loader")
        return expected

    manager = SnapshotManager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock=clock,
    )
    try:
        assert manager.get().status == "loading"
        assert first_started.wait(2)

        clock.advance(timedelta(seconds=301))
        first_release.set()
        assert manager.wait_for_idle(2) is True

        immediate_views = [manager.get() for _ in range(10)]
        assert all(view.status == "ready" for view in immediate_views)
        assert calls == [1]

        clock.advance(timedelta(seconds=299))
        assert manager.get().status == "ready"
        assert calls == [1]

        clock.advance(timedelta(seconds=1))
        boundary = manager.get()
        assert boundary.status == "refreshing"
        assert second_started.wait(2)
        assert calls == [1, 2]
    finally:
        first_release.set()
        second_release.set()
        manager.wait_for_idle(2)
        manager.close()


def test_persisted_recent_commit_mtime_overrides_old_generated_at(tmp_path: Path):
    """Ignoring a recent persisted commit forces a needless restart refresh."""
    clock = FakeClock(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    persisted = _snapshot(NOW - timedelta(days=1))
    store.save(persisted)
    snapshot_path = tmp_path / "cache" / "dashboard_snapshot.json"
    os.utime(snapshot_path, (NOW.timestamp(), NOW.timestamp()))
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("load")
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return _snapshot(clock())

    manager = SnapshotManager(loader, store, clock=clock)
    try:
        assert manager.get().status == "ready"
        assert calls == []

        clock.advance(timedelta(seconds=299))
        assert manager.get().status == "ready"
        assert calls == []

        clock.advance(timedelta(seconds=1))
        assert manager.get().status == "refreshing"
        assert started.wait(2)
        assert calls == ["load"]
    finally:
        release.set()
        manager.wait_for_idle(2)
        manager.close()


def test_persisted_old_commit_mtime_starts_refresh(tmp_path: Path):
    """Treating every persisted snapshot as fresh can serve stale data indefinitely."""
    clock = FakeClock(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    persisted = _snapshot(NOW - timedelta(days=1))
    store.save(persisted)
    snapshot_path = tmp_path / "cache" / "dashboard_snapshot.json"
    old_commit = NOW - timedelta(seconds=600)
    os.utime(snapshot_path, (old_commit.timestamp(), old_commit.timestamp()))
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("load")
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return _snapshot(clock())

    manager = SnapshotManager(loader, store, clock=clock)
    try:
        assert manager.get().status == "refreshing"
        assert started.wait(2)
        assert calls == ["load"]
    finally:
        release.set()
        manager.wait_for_idle(2)
        manager.close()


def test_future_commit_mtime_falls_back_to_generated_at(tmp_path: Path):
    """Trusting a future file mtime grants an unbounded freshness window."""
    clock = FakeClock(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    persisted = _snapshot(NOW - timedelta(seconds=100))
    store.save(persisted)
    snapshot_path = tmp_path / "cache" / "dashboard_snapshot.json"
    future_commit = NOW + timedelta(hours=1)
    os.utime(snapshot_path, (future_commit.timestamp(), future_commit.timestamp()))
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("load")
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return _snapshot(clock())

    manager = SnapshotManager(loader, store, clock=clock)
    try:
        assert manager.get().status == "ready"
        assert calls == []

        clock.advance(timedelta(seconds=200))
        assert manager.get().status == "refreshing"
        assert started.wait(2)
        assert calls == ["load"]
    finally:
        release.set()
        manager.wait_for_idle(2)
        manager.close()


def test_twenty_simultaneous_stale_gets_start_one_loader(tmp_path: Path):
    """Missing single-flight locking permits concurrent refresh jobs."""
    clock = FakeClock(NOW)
    initial = _snapshot(NOW)
    refreshed = _snapshot(NOW + timedelta(seconds=301))
    started = threading.Event()
    release = threading.Event()
    start_gate = threading.Barrier(21)
    calls: list[int] = []

    def loader() -> DashboardSnapshot:
        call_number = len(calls) + 1
        calls.append(call_number)
        if call_number == 1:
            return initial
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return refreshed

    with _manager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock,
    ) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True
        clock.advance(timedelta(seconds=301))

        def concurrent_get(_: int):
            start_gate.wait(timeout=5)
            return manager.get()

        with ThreadPoolExecutor(max_workers=20) as callers:
            futures = [callers.submit(concurrent_get, index) for index in range(20)]
            start_gate.wait(timeout=5)
            views = [future.result(timeout=5) for future in futures]

        assert started.wait(2)
        assert calls == [1, 2]
        assert all(view.status == "refreshing" for view in views)
        assert all(view.snapshot == initial for view in views)

        release.set()
        assert manager.wait_for_idle(2) is True
        assert manager.get().snapshot == refreshed


def test_failed_refresh_preserves_last_good_and_stores_only_fixed_code(tmp_path: Path):
    """Replacing the snapshot or retaining an exception leaks data after failure."""
    clock = FakeClock(NOW)
    initial = _snapshot(NOW)
    calls = 0

    def loader() -> DashboardSnapshot:
        nonlocal calls
        calls += 1
        if calls == 1:
            return initial
        raise LangfuseAPIError("GET", "/api/sk-secret-value/0901234567", 503)

    store = ProtectedSnapshotStore(tmp_path / "cache")
    with _manager(loader, store, clock) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True

        clock.advance(timedelta(seconds=60))
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        failed = manager.get()

        assert failed.status == "stale_error"
        assert failed.snapshot == initial
        assert failed.refreshing is False
        assert failed.last_error_code == "langfuse_unavailable"
        assert failed.last_error_at == NOW + timedelta(seconds=60)
        assert store.load() == initial
        assert "sk-secret-value" not in repr(failed)
        assert "0901234567" not in repr(failed)


def test_completed_automatic_refresh_blocks_manual_force_for_60_seconds(
    tmp_path: Path,
):
    """Forgetting automatic attempts lets a viewer force another costly load immediately."""
    clock = FakeClock(NOW)
    calls: list[datetime] = []

    def loader() -> DashboardSnapshot:
        calls.append(clock())
        return _snapshot(clock())

    with _manager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock,
    ) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW]

        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW]

        clock.advance(timedelta(seconds=59))
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW]

        clock.advance(timedelta(seconds=1))
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW, NOW + timedelta(seconds=60)]


def test_completed_manual_refresh_blocks_sequential_force_for_60_seconds(
    tmp_path: Path,
):
    """Single-flight alone does not stop sequential manual refresh hammering."""
    clock = FakeClock(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    store.save(_snapshot(NOW))
    calls: list[datetime] = []

    def loader() -> DashboardSnapshot:
        calls.append(clock())
        return _snapshot(clock())

    with _manager(loader, store, clock) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW]

        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW]

        clock.advance(timedelta(seconds=59))
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW]

        clock.advance(timedelta(seconds=1))
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW, NOW + timedelta(seconds=60)]


def test_failed_refresh_gets_manual_cooldown_and_keeps_automatic_retry(
    tmp_path: Path,
):
    """A failure must not permit force-spam or suppress the existing 60-second retry."""
    clock = FakeClock(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    last_good = _snapshot(NOW - timedelta(seconds=301))
    store.save(last_good)
    calls: list[datetime] = []

    def loader() -> DashboardSnapshot:
        calls.append(clock())
        if len(calls) == 1:
            raise RuntimeError("upstream unavailable")
        return _snapshot(clock())

    with _manager(loader, store, clock) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        failed = manager.peek()
        assert failed.status == "stale_error"
        assert failed.snapshot == last_good
        assert failed.last_error_code == "refresh_failed"
        assert calls == [NOW]

        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert calls == [NOW]

        clock.advance(timedelta(seconds=59))
        manager.request_refresh(force=True)
        assert manager.get().status == "stale_error"
        assert calls == [NOW]

        clock.advance(timedelta(seconds=1))
        manager.get()
        assert manager.wait_for_idle(2) is True
        ready = manager.peek()
        assert calls == [NOW, NOW + timedelta(seconds=60)]
        assert ready.status == "ready"
        assert ready.last_error_code is None


def test_forced_refresh_joins_an_active_refresh(tmp_path: Path):
    """Force must not bypass single-flight and start a second loader."""
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def loader() -> DashboardSnapshot:
        calls.append("load")
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return _snapshot(NOW)

    clock = FakeClock(NOW)
    with _manager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock,
    ) as manager:
        first = manager.get()
        assert started.wait(2)
        joined = manager.request_refresh(force=True)

        assert first.status == "loading"
        assert joined.status == "loading"
        assert calls == ["load"]

        release.set()
        assert manager.wait_for_idle(2) is True
        assert manager.get().status == "ready"


def test_disk_save_load_round_trips_with_private_modes(tmp_path: Path):
    """Permissive directory/file modes expose the protected snapshot."""
    directory = tmp_path / "runtime" / "dashboard"
    store = ProtectedSnapshotStore(directory)
    expected = _snapshot(NOW)

    assert store.load() is None
    store.save(expected)

    snapshot_path = directory / "dashboard_snapshot.json"
    assert store.load() == expected
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(snapshot_path.stat().st_mode) == 0o600
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == expected.storage_dict()


def test_incompatible_persisted_schema_is_not_served_while_refreshing(
    tmp_path: Path,
):
    """A pre-ticket-scope snapshot must not remain the last-good browser payload."""
    directory = tmp_path / "runtime" / "dashboard"
    directory.mkdir(parents=True)
    legacy_value = _snapshot(NOW).storage_dict()
    legacy_value["schema_version"] = 1
    (directory / "dashboard_snapshot.json").write_text(
        json.dumps(legacy_value),
        encoding="utf-8",
    )
    started = threading.Event()
    release = threading.Event()

    def loader() -> DashboardSnapshot:
        started.set()
        if not release.wait(5):
            raise TimeoutError("test did not release loader")
        return _snapshot(NOW)

    manager = SnapshotManager(
        loader,
        ProtectedSnapshotStore(directory),
        clock=FakeClock(NOW),
    )
    try:
        view = manager.get()

        assert view.status == "loading"
        assert view.snapshot is None
        assert started.wait(2)
    finally:
        release.set()
        manager.wait_for_idle(2)
        manager.close()


def test_save_finishes_permission_changes_before_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A fallible final-path chmod can report failure after committing the snapshot."""
    directory = tmp_path / "runtime" / "dashboard"
    snapshot_path = directory / "dashboard_snapshot.json"
    store = ProtectedSnapshotStore(directory)
    expected = _snapshot(NOW)
    real_chmod = dashboard_cache.os.chmod

    def reject_post_commit_chmod(path: str | Path, mode: int) -> None:
        if Path(path) == snapshot_path:
            raise OSError("permission change attempted after atomic commit")
        real_chmod(path, mode)

    monkeypatch.setattr(dashboard_cache.os, "chmod", reject_post_commit_chmod)

    store.save(expected)

    assert store.load() == expected
    assert stat.S_IMODE(snapshot_path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (LangfuseAPIError("GET", "/api", 503), "langfuse_unavailable"),
        (ValueError("invalid upstream body"), "data_validation_failed"),
        (InvariantError("invalid report"), "data_validation_failed"),
        (RuntimeError("unexpected"), "refresh_failed"),
    ],
)
def test_refresh_errors_are_mapped_to_fixed_codes(
    tmp_path: Path,
    error: Exception,
    expected_code: str,
):
    """Returning arbitrary exception text makes the cache error state unsafe."""
    clock = FakeClock(NOW)

    def loader() -> DashboardSnapshot:
        raise error

    with _manager(
        loader,
        ProtectedSnapshotStore(tmp_path / expected_code),
        clock,
    ) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True
        view = manager.get()

        assert view.status == "stale_error"
        assert view.snapshot is None
        assert view.last_error_code == expected_code
        assert str(error) not in repr(view)


def test_secret_failure_is_not_persisted_and_automatic_retry_waits_60_seconds(
    tmp_path: Path,
):
    """Polling must neither persist exception text nor spin before backoff expires."""
    secret = "upstream body sk-secret-value for 0901234567"
    clock = FakeClock(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    last_good = _snapshot(NOW - timedelta(seconds=301))
    store.save(last_good)
    calls = 0

    def loader() -> DashboardSnapshot:
        nonlocal calls
        calls += 1
        raise RuntimeError(secret)

    with _manager(loader, store, clock) as manager:
        first = manager.get()
        assert first.status == "refreshing"
        assert manager.wait_for_idle(2) is True
        failed = manager.get()

        snapshot_path = tmp_path / "cache" / "dashboard_snapshot.json"
        assert failed.status == "stale_error"
        assert failed.last_error_code == "refresh_failed"
        assert secret not in repr(failed)
        assert "sk-secret-value" not in snapshot_path.read_text(encoding="utf-8")
        assert "0901234567" not in snapshot_path.read_text(encoding="utf-8")
        assert "sk-secret-value" not in failed.last_error_code
        assert "0901234567" not in failed.last_error_code

        clock.advance(timedelta(seconds=59))
        before_retry = manager.get()
        assert before_retry.status == "stale_error"
        assert calls == 1

        clock.advance(timedelta(seconds=2))
        retrying = manager.get()
        assert retrying.status == "refreshing"
        assert manager.wait_for_idle(2) is True
        assert calls == 2


def test_loader_failure_logs_only_a_fixed_code(tmp_path: Path, caplog):
    secret = "sk-secret-value 0901234567 trace-abc identity@example.test"

    def loader() -> DashboardSnapshot:
        raise RuntimeError(secret)

    with _manager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        FakeClock(NOW),
    ) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "weekly_cs_report.runtime"
    ]
    assert {"event": "refresh_failure", "code": "refresh_failed"} in events
    assert secret not in caplog.text
    assert "0901234567" not in caplog.text
    assert "trace-abc" not in caplog.text
    assert "identity@example.test" not in caplog.text


def test_successful_refresh_emits_allowlisted_snapshot_aggregates(tmp_path: Path, caplog):
    with _manager(
        lambda: _snapshot(NOW),
        ProtectedSnapshotStore(tmp_path / "cache"),
        FakeClock(NOW),
    ) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "weekly_cs_report.runtime"
    ]
    success = next(event for event in events if event["event"] == "refresh_success")
    assert success.items() >= {
        "event": "refresh_success",
        "schema_version": 24,
        "ticket_count": 0,
        "trace_count": 0,
        "observation_count": 0,
        "coverage_issue_category": 0.0,
        "coverage_app": 0.0,
        "coverage_tpe": 0.0,
        "coverage_intent": 0.0,
        "coverage_skill": 0.0,
    }.items()
    assert isinstance(success["duration_ms"], int)
    assert success["duration_ms"] >= 0


def test_shutdown_cancellation_logs_cancelled_not_failure(tmp_path: Path, caplog):
    started = threading.Event()
    cancellation = threading.Event()

    def loader() -> DashboardSnapshot:
        started.set()
        assert cancellation.wait(timeout=2)
        raise LangfuseRequestCancelled("GET", "/api/public/traces")

    manager = SnapshotManager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock=FakeClock(NOW),
        cancel_event=cancellation,
    )
    manager.get()
    assert started.wait(timeout=2)
    manager.close()

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "weekly_cs_report.runtime"
    ]
    assert {"event": "refresh_cancelled", "code": "cancelled"} in events
    assert not any(event["event"] == "refresh_failure" for event in events)


@pytest.mark.parametrize(
    ("stage", "loader"),
    [
        ("refresh_start", lambda: pytest.fail("loader must not run after start log failure")),
        ("refresh_failure", lambda: (_ for _ in ()).throw(RuntimeError("sk-secret-value 0901234567"))),
        ("refresh_cancelled", lambda: (_ for _ in ()).throw(LangfuseRequestCancelled("GET", "/api/public/traces"))),
        ("refresh_success", lambda: _snapshot(NOW + timedelta(seconds=1))),
    ],
)
def test_log_failure_never_leaves_refresh_active_or_replaces_last_good(
    tmp_path: Path,
    monkeypatch,
    caplog,
    stage: str,
    loader,
):
    initial = _snapshot(NOW)
    store = ProtectedSnapshotStore(tmp_path / stage)
    store.save(initial)
    secret = "logger sk-secret-value 0901234567 trace-abc identity@example.test"

    def fail_stage(event: str, **_fields: object) -> None:
        if event == stage:
            raise RuntimeError(secret)

    monkeypatch.setattr(dashboard_cache, "emit_event", fail_stage)
    with _manager(loader, store, FakeClock(NOW)) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        view = manager.peek()

    assert view.refreshing is False
    assert view.status == "stale_error"
    assert view.snapshot == initial
    assert view.last_error_code in {
        "langfuse_unavailable",
        "data_validation_failed",
        "refresh_failed",
    }
    assert secret not in repr(view)
    assert "0901234567" not in repr(view)
    assert "trace-abc" not in repr(view)
    assert "identity@example.test" not in repr(view)
    assert secret not in caplog.text
    assert "0901234567" not in caplog.text


def test_success_log_failure_restores_the_previous_snapshot_on_disk(
    tmp_path: Path,
    monkeypatch,
):
    initial = _snapshot(NOW)
    store = ProtectedSnapshotStore(tmp_path / "cache")
    store.save(initial)

    def fail_success(event: str, **_fields: object) -> None:
        if event == "refresh_success":
            raise RuntimeError("logger failure")

    monkeypatch.setattr(dashboard_cache, "emit_event", fail_success)
    with _manager(
        lambda: _snapshot(NOW + timedelta(seconds=1)),
        store,
        FakeClock(NOW),
    ) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        assert manager.peek().snapshot == initial

    assert ProtectedSnapshotStore(tmp_path / "cache").load() == initial


def test_success_log_failure_removes_an_unacknowledged_first_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    store = ProtectedSnapshotStore(tmp_path / "cache")

    def fail_success(event: str, **_fields: object) -> None:
        if event == "refresh_success":
            raise RuntimeError("logger failure")

    monkeypatch.setattr(dashboard_cache, "emit_event", fail_success)
    with _manager(lambda: _snapshot(NOW), store, FakeClock(NOW)) as manager:
        manager.get()
        assert manager.wait_for_idle(2) is True
        assert manager.peek().snapshot is None

    assert not (tmp_path / "cache" / "dashboard_snapshot.json").exists()


def test_rollback_failure_keeps_the_committed_snapshot_in_memory_and_on_disk(
    tmp_path: Path,
    monkeypatch,
):
    initial = _snapshot(NOW)
    replacement = _snapshot(NOW + timedelta(seconds=1))
    store = ProtectedSnapshotStore(tmp_path / "cache")
    store.save(initial)

    def fail_success(event: str, **_fields: object) -> None:
        if event == "refresh_success":
            raise RuntimeError("logger failure")

    def fail_rollback(_snapshot: DashboardSnapshot | None) -> None:
        raise OSError("restore failed")

    monkeypatch.setattr(dashboard_cache, "emit_event", fail_success)
    monkeypatch.setattr(store, "restore", fail_rollback, raising=False)
    with _manager(lambda: replacement, store, FakeClock(NOW)) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        view = manager.peek()

    assert view.status == "stale_error"
    assert view.last_error_code == "refresh_failed"
    assert view.snapshot == replacement
    assert ProtectedSnapshotStore(tmp_path / "cache").load() == replacement


@pytest.mark.parametrize("has_previous", (False, True))
def test_replace_that_commits_then_raises_is_reconciled_as_success(
    tmp_path: Path,
    monkeypatch,
    caplog,
    has_previous: bool,
):
    store = ProtectedSnapshotStore(tmp_path / "cache")
    previous = _snapshot(NOW)
    replacement = _snapshot(NOW + timedelta(seconds=1))
    if has_previous:
        store.save(previous)
    real_replace = dashboard_cache.os.replace
    secret = "late replace sk-secret-value 0901234567 trace-abc"

    def replace_then_raise(source: str | Path, destination: str | Path) -> None:
        real_replace(source, destination)
        raise OSError(secret)

    monkeypatch.setattr(dashboard_cache.os, "replace", replace_then_raise)
    with _manager(lambda: replacement, store, FakeClock(NOW)) as manager:
        if has_previous:
            manager.request_refresh(force=True)
        else:
            manager.get()
        assert manager.wait_for_idle(2) is True
        view = manager.peek()

    assert view.status == "ready"
    assert view.refreshing is False
    assert view.last_error_code is None
    assert view.snapshot == replacement
    assert ProtectedSnapshotStore(tmp_path / "cache").load() == replacement
    assert secret not in caplog.text
    assert "0901234567" not in caplog.text
    assert "trace-abc" not in caplog.text


@pytest.mark.parametrize("has_previous", (False, True))
def test_post_save_clock_failure_rolls_back_durable_snapshot(
    tmp_path: Path,
    caplog,
    has_previous: bool,
):
    store = ProtectedSnapshotStore(tmp_path / "cache")
    previous = _snapshot(NOW)
    replacement = _snapshot(NOW + timedelta(seconds=1))
    if has_previous:
        store.save(previous)
    secret = "clock sk-secret-value 0901234567 identity@example.test"
    clock = FailOnCallClock(NOW, fail_call=2, error=RuntimeError(secret))

    with _manager(lambda: replacement, store, clock) as manager:
        if has_previous:
            manager.request_refresh(force=True)
        else:
            manager.get()
        assert manager.wait_for_idle(2) is True
        view = manager.peek()

    assert view.status == "stale_error"
    assert view.refreshing is False
    assert view.last_error_code == "refresh_failed"
    assert view.snapshot == (previous if has_previous else None)
    assert ProtectedSnapshotStore(tmp_path / "cache").load() == (
        previous if has_previous else None
    )
    assert secret not in caplog.text
    assert "0901234567" not in caplog.text
    assert "identity@example.test" not in caplog.text


def test_restore_that_commits_then_raises_preserves_prior_and_original_error(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    store = ProtectedSnapshotStore(tmp_path / "cache")
    previous = _snapshot(NOW)
    replacement = _snapshot(NOW + timedelta(seconds=1))
    store.save(previous)
    secret = "late restore sk-secret-value 0901234567 trace-abc"
    clock = FailOnCallClock(NOW, fail_call=2, error=ValueError(secret))
    real_replace = dashboard_cache.os.replace
    replace_calls = 0

    def fail_after_restore_replace(
        source: str | Path,
        destination: str | Path,
    ) -> None:
        nonlocal replace_calls
        replace_calls += 1
        real_replace(source, destination)
        if replace_calls == 2:
            raise OSError(secret)

    monkeypatch.setattr(dashboard_cache.os, "replace", fail_after_restore_replace)
    with _manager(lambda: replacement, store, clock) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        view = manager.peek()

    assert replace_calls == 2
    assert view.status == "stale_error"
    assert view.last_error_code == "data_validation_failed"
    assert view.snapshot == previous
    assert ProtectedSnapshotStore(tmp_path / "cache").load() == previous
    assert secret not in caplog.text
    assert "0901234567" not in caplog.text
    assert "trace-abc" not in caplog.text


def test_restore_failure_before_replace_aligns_memory_to_committed_new_snapshot(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    store = ProtectedSnapshotStore(tmp_path / "cache")
    previous = _snapshot(NOW)
    replacement = _snapshot(NOW + timedelta(seconds=1))
    store.save(previous)
    secret = "early restore sk-secret-value 0901234567 trace-abc"
    clock = FailOnCallClock(NOW, fail_call=2, error=ValueError(secret))
    real_replace = dashboard_cache.os.replace
    replace_calls = 0

    def fail_before_restore_replace(
        source: str | Path,
        destination: str | Path,
    ) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError(secret)
        real_replace(source, destination)

    monkeypatch.setattr(dashboard_cache.os, "replace", fail_before_restore_replace)
    with _manager(lambda: replacement, store, clock) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        view = manager.peek()

    assert replace_calls == 2
    assert view.status == "stale_error"
    assert view.last_error_code == "refresh_failed"
    assert view.snapshot == replacement
    assert ProtectedSnapshotStore(tmp_path / "cache").load() == replacement
    assert secret not in caplog.text
    assert "0901234567" not in caplog.text
    assert "trace-abc" not in caplog.text


def test_unreadable_durable_state_uses_conservative_no_snapshot_fallback(
    tmp_path: Path,
    monkeypatch,
):
    store = ProtectedSnapshotStore(tmp_path / "cache")
    previous = _snapshot(NOW)
    replacement = _snapshot(NOW + timedelta(seconds=1))
    store.save(previous)
    clock = FailOnCallClock(NOW, fail_call=2, error=RuntimeError("clock failed"))
    real_replace = dashboard_cache.os.replace
    replace_calls = 0

    def fail_before_restore_replace(
        source: str | Path,
        destination: str | Path,
    ) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("restore failed")
        real_replace(source, destination)

    monkeypatch.setattr(dashboard_cache.os, "replace", fail_before_restore_replace)
    monkeypatch.setattr(
        store,
        "_read_snapshot_without_event",
        lambda: (False, None),
        raising=False,
    )
    with _manager(lambda: replacement, store, clock) as manager:
        manager.request_refresh(force=True)
        assert manager.wait_for_idle(2) is True
        view = manager.peek()

    assert view.status == "stale_error"
    assert view.last_error_code == "refresh_failed"
    assert view.snapshot is None
    assert view.refreshing is False


def test_close_is_idempotent(tmp_path: Path):
    """Repeated lifecycle shutdown must not fail."""
    clock = FakeClock(NOW)
    manager = SnapshotManager(
        lambda: _snapshot(NOW),
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock=clock,
    )

    manager.close()
    manager.close()


def test_close_sets_process_cancellation_before_waiting_for_refresh(tmp_path: Path):
    """Shutdown must signal an active loader before joining its executor thread."""
    started = threading.Event()
    observed_cancellation = threading.Event()
    cancellation = threading.Event()

    def loader() -> DashboardSnapshot:
        started.set()
        if cancellation.wait(timeout=2):
            observed_cancellation.set()
            return _snapshot(NOW)
        raise TimeoutError("close did not signal cancellation")

    manager = SnapshotManager(
        loader,
        ProtectedSnapshotStore(tmp_path / "cache"),
        clock=FakeClock(NOW),
        cancel_event=cancellation,
    )
    manager.get()
    assert started.wait(timeout=2)

    manager.close()

    assert observed_cancellation.is_set()
    manager.close()
