from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from .dashboard_schema import _STORAGE_VERSION, DashboardSnapshot
from .langfuse_client import LangfuseAPIError, LangfuseRequestCancelled
from .models import InvariantError
from .runtime_logging import emit_event


_SNAPSHOT_FILENAME = "dashboard_snapshot.json"
_AUTOMATIC_RETRY_DELAY = timedelta(seconds=60)
# The heartbeat only *asks*; the TTL still decides. Asking every minute
# keeps a settled snapshot within a minute of its 300s expiry without
# adding a single extra upstream read.
_HEARTBEAT_INTERVAL_SECONDS = 60.0
_MANUAL_REFRESH_COOLDOWN = timedelta(seconds=60)
_KEEP_SNAPSHOT = object()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CacheView:
    status: str
    snapshot: DashboardSnapshot | None
    refreshing: bool
    last_error_code: str | None
    last_error_at: datetime | None


class ProtectedSnapshotStore:
    def __init__(
        self,
        directory: Path,
        *,
        require_complete_enrichment: bool = False,
    ) -> None:
        self._directory = Path(directory)
        self._snapshot_path = self._directory / _SNAPSHOT_FILENAME
        self._require_complete_enrichment = require_complete_enrichment

    def load(self) -> DashboardSnapshot | None:
        if not self._snapshot_path.exists():
            return None
        try:
            with self._snapshot_path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
            snapshot = DashboardSnapshot.from_storage_dict(value)
            if self._require_complete_enrichment and not _has_complete_enrichment(
                snapshot
            ):
                emit_event(
                    "snapshot_load_ignored",
                    code="incomplete_enrichment",
                )
                return None
            return snapshot
        except (json.JSONDecodeError, ValueError):
            # Older schemas lack the current weekly privacy/metric contract.
            # Do not attempt a lossy conversion; bootstrap with a fresh run.
            emit_event("snapshot_load_ignored", code="invalid_snapshot")
            return None

    def snapshot_mtime(self) -> datetime | None:
        try:
            modified_at = self._snapshot_path.stat().st_mtime
        except FileNotFoundError:
            return None
        return datetime.fromtimestamp(modified_at, tz=timezone.utc)

    def save(self, snapshot: DashboardSnapshot) -> None:
        if self._require_complete_enrichment and not _has_complete_enrichment(
            snapshot
        ):
            raise InvariantError("enrichment is incomplete")
        value = snapshot.storage_dict()
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._directory, 0o700)

        descriptor: int | None = None
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".dashboard_snapshot.",
                suffix=".tmp",
                dir=self._directory,
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = None
                json.dump(
                    value,
                    stream,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._snapshot_path)
            temporary_path = None
        except Exception:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            if self._matches_snapshot(snapshot):
                return
            raise

    def restore(self, snapshot: DashboardSnapshot | None) -> None:
        """Restore the last acknowledged snapshot after a terminal log failure."""

        if snapshot is not None:
            self.save(snapshot)
            return
        try:
            self._snapshot_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            readable, persisted = self._read_snapshot_without_event()
            if readable and persisted is None:
                return
            raise

    def _matches_snapshot(self, snapshot: DashboardSnapshot) -> bool:
        readable, persisted = self._read_snapshot_without_event()
        return readable and persisted == snapshot

    def _read_snapshot_without_event(
        self,
    ) -> tuple[bool, DashboardSnapshot | None]:
        try:
            with self._snapshot_path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
            return True, DashboardSnapshot.from_storage_dict(value)
        except FileNotFoundError:
            return True, None
        except (OSError, TypeError, ValueError):
            return False, None


def _has_complete_enrichment(snapshot: DashboardSnapshot) -> bool:
    return snapshot.dashboard.get("enrichment_status") == "complete"


class SnapshotManager:
    def __init__(
        self,
        loader: Callable[[], DashboardSnapshot],
        store: ProtectedSnapshotStore,
        *,
        ttl: timedelta = timedelta(seconds=300),
        clock: Callable[[], datetime] = utc_now,
        cancel_event: threading.Event | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._store = store
        self._ttl = ttl
        self._clock = clock
        self._cancel_event = cancel_event or threading.Event()
        self._monotonic = monotonic
        initial_snapshot = store.load()
        initial_success_at: datetime | None = None
        persisted_mtime: datetime | None = None
        if initial_snapshot is not None:
            initial_success_at = initial_snapshot.generated_at.astimezone(timezone.utc)
            persisted_mtime = store.snapshot_mtime()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        with self._lock:
            self._snapshot = initial_snapshot
            self._last_success_at = initial_success_at
            self._persisted_mtime = persisted_mtime
            self._future: Future[None] | None = None
            self._last_error_code: str | None = None
            self._last_error_at: datetime | None = None
            self._next_automatic_retry_at: datetime | None = None
            self._next_manual_refresh_at: datetime | None = None
            self._closed = False
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def get(self) -> CacheView:
        with self._lock:
            now = self._utc_clock()
            if self._should_refresh_automatically(now):
                self._start_refresh()
            return self._view()

    def peek(self) -> CacheView:
        with self._lock:
            return self._view()

    def request_refresh(self, *, force: bool = False) -> CacheView:
        with self._lock:
            now = self._utc_clock()
            if (
                self._future is None
                and not self._closed
                and (
                    (force and self._manual_refresh_allowed(now))
                    or (not force and self._should_refresh_automatically(now))
                )
            ):
                self._start_refresh()
            return self._view()

    def wait_for_idle(self, timeout_seconds: float) -> bool:
        with self._lock:
            future = self._future
        if future is None:
            return True
        try:
            future.result(timeout=timeout_seconds)
        except FutureTimeout:
            return False
        except Exception:
            return True
        return True

    def start_background_refresh(
        self,
        *,
        interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        """Keep the snapshot fresh when nobody is looking at it.

        The TTL is only ever consulted from ``get()``, so without this the
        dashboard is live-on-open and nothing else: leave it unopened
        overnight and the first reader next morning is served yesterday's
        numbers, then waits out a full pipeline run. This ticks ``get()`` on
        the manager's behalf, which means the refresh it triggers is the same
        one a reader triggers -- same TTL, same single-flight ``_future``,
        same 60s backoff after a failure. Nothing here decides to refresh;
        it only makes sure someone asks.

        Opt-in, and started only by the serving process: a test or a CLI that
        builds a manager must not acquire a thread that calls Langfuse.
        """
        with self._lock:
            if self._closed or self._heartbeat_thread is not None:
                return
            thread = threading.Thread(
                target=self._heartbeat,
                args=(interval_seconds,),
                name="dashboard-snapshot-heartbeat",
                daemon=True,
            )
            self._heartbeat_thread = thread
        thread.start()

    def _heartbeat(self, interval_seconds: float) -> None:
        # Waiting first, not last: startup already reads the snapshot, and a
        # tick landing on top of that would only contend for the same lock.
        while not self._heartbeat_stop.wait(interval_seconds):
            try:
                self.get()
            except Exception:
                # A refresh failure is already recorded on the view by
                # _refresh; what reaches here is the read path itself
                # breaking -- a clock that raises, say. Letting that kill the
                # loop would silently return the process to live-on-open,
                # which is the exact failure this method exists to prevent.
                _emit_event_safely("heartbeat_tick_failed", code="tick_failed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._heartbeat_thread
            self._heartbeat_thread = None
            self._cancel_event.set()
        # Join outside the lock: the heartbeat takes it on every tick, so
        # joining while holding it deadlocks shutdown.
        self._heartbeat_stop.set()
        if thread is not None:
            thread.join(timeout=5.0)
        self._executor.shutdown(wait=True)

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    def _should_refresh_automatically(self, now: datetime) -> bool:
        if self._closed or self._future is not None:
            return False
        if (
            self._next_automatic_retry_at is not None
            and now < self._next_automatic_retry_at
        ):
            return False
        if self._snapshot is None:
            return True
        if self._persisted_mtime is not None:
            if self._persisted_mtime <= now:
                self._last_success_at = max(
                    self._last_success_at
                    or self._snapshot.generated_at.astimezone(timezone.utc),
                    self._persisted_mtime,
                )
            self._persisted_mtime = None
        if self._last_success_at is None:
            return True
        return now - self._last_success_at >= self._ttl

    def _start_refresh(self) -> None:
        if self._closed or self._future is not None:
            return
        self._future = self._executor.submit(self._refresh)

    def _refresh(self) -> None:
        started_at = self._monotonic()
        with self._lock:
            has_snapshot = self._snapshot is not None
            previous_snapshot = self._snapshot
        refreshed_snapshot: DashboardSnapshot | None = None
        candidate_snapshot: DashboardSnapshot | None = None
        success_at: datetime | None = None
        error_code = "refresh_failed"
        failure_snapshot: object | DashboardSnapshot | None = _KEEP_SNAPSHOT
        persistence_attempted = False
        try:
            emit_event("refresh_start", has_snapshot=has_snapshot)
            snapshot = self._loader()
            if self._cancel_event.is_set():
                raise LangfuseRequestCancelled("GET", "/api/public/traces")
            if not isinstance(snapshot, DashboardSnapshot):
                raise ValueError("loader did not return DashboardSnapshot")
            snapshot.storage_dict()
            candidate_snapshot = snapshot
            persistence_attempted = True
            self._store.save(snapshot)
            success_at = self._utc_clock()
        except LangfuseRequestCancelled:
            error_code = "langfuse_unavailable"
            if not _emit_event_safely("refresh_cancelled", code="cancelled"):
                error_code = "refresh_failed"
        except Exception as error:
            error_code = _error_code(error)
            if persistence_attempted and candidate_snapshot is not None:
                failure_snapshot, restored = self._rollback_or_align_persisted_snapshot(
                    previous_snapshot
                )
                if not restored:
                    error_code = "refresh_failed"
            if not _emit_event_safely("refresh_failure", code=error_code):
                error_code = "refresh_failed"
        else:
            try:
                success_fields = _refresh_success_fields(
                    snapshot,
                    duration_ms=max(0, int((self._monotonic() - started_at) * 1000)),
                )
            except Exception:
                error_code = "refresh_failed"
            else:
                if _emit_event_safely("refresh_success", **success_fields):
                    refreshed_snapshot = snapshot
                else:
                    error_code = "refresh_failed"
            if refreshed_snapshot is None:
                (
                    failure_snapshot,
                    restored,
                ) = self._rollback_or_align_persisted_snapshot(
                    previous_snapshot
                )
                if not restored:
                    error_code = "refresh_failed"
        finally:
            if refreshed_snapshot is not None and success_at is not None:
                self._finish_successful_refresh(refreshed_snapshot, success_at)
            else:
                self._finish_failed_refresh(
                    error_code,
                    self._safe_error_time(),
                    snapshot=failure_snapshot,
                )

    def _finish_successful_refresh(
        self,
        snapshot: DashboardSnapshot,
        success_at: datetime,
    ) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._last_success_at = success_at
            self._persisted_mtime = None
            self._last_error_code = None
            self._last_error_at = None
            self._next_automatic_retry_at = None
            self._next_manual_refresh_at = success_at + _MANUAL_REFRESH_COOLDOWN
            self._future = None

    def _finish_failed_refresh(
        self,
        error_code: str,
        error_at: datetime,
        *,
        snapshot: object | DashboardSnapshot | None = _KEEP_SNAPSHOT,
    ) -> None:
        with self._lock:
            if snapshot is not _KEEP_SNAPSHOT:
                self._snapshot = snapshot
            self._last_error_code = error_code
            self._last_error_at = error_at
            self._next_automatic_retry_at = error_at + _AUTOMATIC_RETRY_DELAY
            self._next_manual_refresh_at = error_at + _MANUAL_REFRESH_COOLDOWN
            self._future = None

    def _rollback_or_align_persisted_snapshot(
        self,
        previous_snapshot: DashboardSnapshot | None,
    ) -> tuple[object | DashboardSnapshot | None, bool]:
        try:
            self._store.restore(previous_snapshot)
        except Exception:
            readable, persisted = self._store._read_snapshot_without_event()
            # An unreadable file is not a usable snapshot. Serving no in-memory
            # snapshot is the conservative state until storage is repaired.
            return (persisted if readable else None), False
        return _KEEP_SNAPSHOT, True

    def _safe_error_time(self) -> datetime:
        try:
            return self._utc_clock()
        except Exception:
            return utc_now()

    def _view(self) -> CacheView:
        refreshing = self._future is not None
        if refreshing and self._snapshot is None:
            status = "loading"
        elif refreshing:
            status = "refreshing"
        elif self._last_error_code is not None:
            status = "stale_error"
        else:
            status = "ready"
        return CacheView(
            status=status,
            snapshot=self._snapshot,
            refreshing=refreshing,
            last_error_code=self._last_error_code,
            last_error_at=self._last_error_at,
        )

    def _utc_clock(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _manual_refresh_allowed(self, now: datetime) -> bool:
        return (
            self._next_manual_refresh_at is None
            or now >= self._next_manual_refresh_at
        )


def _error_code(error: Exception) -> str:
    if isinstance(error, LangfuseAPIError):
        return "langfuse_unavailable"
    if isinstance(error, (ValueError, InvariantError)):
        return "data_validation_failed"
    return "refresh_failed"


def _emit_event_safely(event: str, **fields: object) -> bool:
    """Return whether a log event was emitted without exposing its failure."""

    try:
        emit_event(event, **fields)
    except Exception:
        return False
    return True


def _refresh_success_fields(
    snapshot: DashboardSnapshot,
    *,
    duration_ms: int,
) -> dict[str, int | float]:
    """Select scalar aggregates without inspecting or serializing ticket rows."""

    fields: dict[str, int | float] = {
        "duration_ms": duration_ms,
        "schema_version": _STORAGE_VERSION,
        "ticket_count": len(snapshot.tickets),
    }
    source = snapshot.dashboard.get("source")
    if isinstance(source, dict):
        for dashboard_name, event_name in (
            ("traces_fetched", "trace_count"),
            ("observations_fetched", "observation_count"),
        ):
            value = source.get(dashboard_name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                fields[event_name] = value
    coverage = snapshot.dashboard.get("coverage")
    if isinstance(coverage, dict):
        for dashboard_name, event_name in (
            ("issue_category", "coverage_issue_category"),
            ("app", "coverage_app"),
            ("tpe", "coverage_tpe"),
            ("intent", "coverage_intent"),
            ("skill", "coverage_skill"),
        ):
            value = coverage.get(dashboard_name)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value >= 0
            ):
                fields[event_name] = value
    return fields
