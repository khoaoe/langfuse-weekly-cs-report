from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
import threading

from .dashboard_schema import DashboardSnapshot
from .langfuse_client import LangfuseAPIError
from .models import InvariantError


_SNAPSHOT_FILENAME = "dashboard_snapshot.json"
_AUTOMATIC_RETRY_DELAY = timedelta(seconds=60)
_MANUAL_REFRESH_COOLDOWN = timedelta(seconds=60)
_LOG = logging.getLogger(__name__)


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
    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._snapshot_path = self._directory / _SNAPSHOT_FILENAME

    def load(self) -> DashboardSnapshot | None:
        if not self._snapshot_path.exists():
            return None
        try:
            with self._snapshot_path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
            return DashboardSnapshot.from_storage_dict(value)
        except (json.JSONDecodeError, ValueError):
            # Older schemas lack the current weekly privacy/metric contract.
            # Do not attempt a lossy conversion; bootstrap with a fresh run.
            _LOG.warning("dashboard snapshot ignored: incompatible or invalid schema")
            return None

    def snapshot_mtime(self) -> datetime | None:
        try:
            modified_at = self._snapshot_path.stat().st_mtime
        except FileNotFoundError:
            return None
        return datetime.fromtimestamp(modified_at, tz=timezone.utc)

    def save(self, snapshot: DashboardSnapshot) -> None:
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
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
            raise


class SnapshotManager:
    def __init__(
        self,
        loader: Callable[[], DashboardSnapshot],
        store: ProtectedSnapshotStore,
        *,
        ttl: timedelta = timedelta(seconds=300),
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._loader = loader
        self._store = store
        self._ttl = ttl
        self._clock = clock
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

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True)

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
        try:
            snapshot = self._loader()
            if not isinstance(snapshot, DashboardSnapshot):
                raise ValueError("loader did not return DashboardSnapshot")
            snapshot.storage_dict()
            self._store.save(snapshot)
            success_at = self._utc_clock()
        except Exception as error:
            error_code = _error_code(error)
            error_at = self._utc_clock()
            with self._lock:
                self._last_error_code = error_code
                self._last_error_at = error_at
                self._next_automatic_retry_at = error_at + _AUTOMATIC_RETRY_DELAY
                self._next_manual_refresh_at = error_at + _MANUAL_REFRESH_COOLDOWN
                self._future = None
            return

        with self._lock:
            self._snapshot = snapshot
            self._last_success_at = success_at
            self._persisted_mtime = None
            self._last_error_code = None
            self._last_error_at = None
            self._next_automatic_retry_at = None
            self._next_manual_refresh_at = success_at + _MANUAL_REFRESH_COOLDOWN
            self._future = None

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
