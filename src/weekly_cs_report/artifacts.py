from __future__ import annotations

import csv
import json
import os
import shutil
import stat
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO

FORBIDDEN_KEYS = frozenset(
    {
        "input",
        "output",
        "comments",
        "user_input",
        "user_id",
        "trans_id",
        "response",
    }
)
_RUN_PREFIX = "run-"
_RUN_RETENTION = 30


class ArtifactSafetyError(ValueError):
    pass


def _safe_name(name: str, suffix: str) -> None:
    path = Path(name)
    if (
        not name
        or path.name != name
        or name in {".", ".."}
        or path.suffix != suffix
    ):
        raise ArtifactSafetyError("artifact name must be one safe file name")


def _assert_safe_keys(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = FORBIDDEN_KEYS.intersection(
            key for key in value if isinstance(key, str)
        )
        if forbidden:
            raise ArtifactSafetyError(
                "artifact contains a forbidden raw-payload key"
            )
        for child in value.values():
            _assert_safe_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_safe_keys(child)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ArtifactSafetyError("artifact datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported artifact value type: {type(value).__name__}")


def _assert_no_symlink_components(path: Path, description: str) -> None:
    """Reject a symlink in any existing path component without resolving it."""
    candidate = Path(path)
    if candidate.is_absolute():
        current = Path(candidate.anchor)
        components = candidate.parts[1:]
    else:
        current = Path.cwd()
        components = candidate.parts

    for component in components:
        current /= component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        except NotADirectoryError as error:
            raise ArtifactSafetyError(f"{description} has an invalid path component") from error
        if stat.S_ISLNK(mode):
            raise ArtifactSafetyError(f"{description} must not contain a symlink")


def _ensure_directory(path: Path, description: str) -> None:
    _assert_no_symlink_components(path, description)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _assert_no_symlink_components(path, description)
    if not path.is_dir():
        raise ArtifactSafetyError(f"{description} must be a directory")
    path.chmod(0o700)


def _assert_directory(path: Path, description: str) -> None:
    _assert_no_symlink_components(path, description)
    if not path.is_dir():
        raise ArtifactSafetyError(f"{description} must be a directory")


def _assert_safe_destination(destination: Path) -> None:
    _assert_no_symlink_components(destination, "artifact destination")
    if destination.exists() and not destination.is_file():
        raise ArtifactSafetyError("artifact destination must be a regular file")


def _assert_latest_directory(latest: Path) -> None:
    _assert_no_symlink_components(latest, "latest artifact path")
    if latest.exists() and not latest.is_dir():
        raise ArtifactSafetyError("latest artifact path must be a directory")


def _create_private_directory(root: Path, prefix: str) -> Path:
    _assert_directory(root, "artifact store root")
    directory = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    _assert_no_symlink_components(directory, "artifact publication directory")
    directory.chmod(0o700)
    return directory


def _remove_private_directory(directory: Path | None) -> None:
    if directory is None or not directory.exists():
        return
    _assert_no_symlink_components(directory, "artifact publication directory")
    shutil.rmtree(directory)


def _best_effort_remove_private_directory(directory: Path | None) -> bool:
    try:
        _remove_private_directory(directory)
    except OSError:
        return False
    return True


def _backup_contains_previous_latest(backup: Path | None, latest: Path) -> bool:
    """Observe a completed first rename in the single-writer publication flow."""
    if backup is None:
        return False
    _assert_no_symlink_components(backup, "artifact publication directory")
    _assert_latest_directory(latest)
    return backup.is_dir() and not latest.exists()


def _restore_latest_from_backup(backup: Path, latest: Path) -> Path | None:
    """Restore the old publication, reconciling a replace that raised late."""
    if not _backup_contains_previous_latest(backup, latest):
        return backup
    try:
        os.replace(backup, latest)
    except OSError:
        _assert_no_symlink_components(backup, "artifact publication directory")
        _assert_latest_directory(latest)
        if not backup.exists() and latest.is_dir():
            return None
        return backup
    return None


def _atomic_write(
    destination: Path,
    write: Callable[[TextIO], None],
    *,
    newline: str | None = None,
) -> None:
    """Commit text content without exposing a partial artifact."""
    _assert_safe_destination(destination)
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        file = os.fdopen(descriptor, "w", encoding="utf-8", newline=newline)
        descriptor = None
        with file:
            write(file)
            file.flush()
            os.fsync(file.fileno())

        # Recheck before final replacement; a concurrent pathname swap remains
        # an operating-system race outside this API's guarantee.
        _assert_safe_destination(destination)
        os.replace(temporary, destination)
        temporary = None
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise


class ProtectedArtifactRun:
    def __init__(self, store: ProtectedArtifactStore, path: Path) -> None:
        self._store = store
        self.path = path

    def write_json(self, name: str, payload: object) -> Path:
        _safe_name(name, ".json")
        _assert_safe_keys(payload)
        _assert_directory(self._store.root, "artifact store root")
        _assert_directory(self.path, "run artifact path")
        destination = self.path / name
        _assert_safe_destination(destination)
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        self._write_text(destination, serialized + "\n")
        return destination

    def write_csv(
        self,
        name: str,
        rows: Sequence[Mapping[str, object]],
        *,
        fieldnames: Sequence[str] | None = None,
    ) -> Path:
        _safe_name(name, ".csv")
        if fieldnames is None:
            fieldnames = tuple(rows[0]) if rows else ()
        if FORBIDDEN_KEYS.intersection(fieldnames):
            raise ArtifactSafetyError(
                "artifact contains a forbidden raw-payload column"
            )
        if any(Path(field).name != field for field in fieldnames):
            raise ArtifactSafetyError("artifact CSV contains an unsafe column")
        for row in rows:
            if set(row) != set(fieldnames):
                raise ArtifactSafetyError(
                    "artifact CSV rows must match the declared columns"
                )
            _assert_safe_keys(row)

        _assert_directory(self._store.root, "artifact store root")
        _assert_directory(self.path, "run artifact path")
        destination = self.path / name
        _assert_safe_destination(destination)

        def write(file: TextIO) -> None:
            writer = csv.DictWriter(file, fieldnames=list(fieldnames))
            writer.writeheader()
            writer.writerows(rows)

        _atomic_write(destination, write, newline="")
        return destination

    def publish_latest(self) -> Path:
        _assert_directory(self._store.root, "artifact store root")
        _assert_directory(self.path, "run artifact path")
        latest = self._store.root / "latest"
        _assert_latest_directory(latest)
        staging = _create_private_directory(self._store.root, ".latest-staging-")
        backup: Path | None = None
        previous_latest_moved = False
        committed = False
        try:
            for source in sorted(self.path.iterdir()):
                if not source.is_file() or source.is_symlink():
                    continue
                destination = staging / source.name
                shutil.copyfile(source, destination)
                destination.chmod(0o600)

            _assert_directory(self._store.root, "artifact store root")
            _assert_latest_directory(latest)
            if latest.exists():
                backup = _create_private_directory(
                    self._store.root, ".latest-backup-"
                )
                backup.rmdir()
                _assert_latest_directory(latest)
                _assert_no_symlink_components(backup, "artifact publication directory")
                os.replace(latest, backup)
                previous_latest_moved = True

            _assert_directory(self._store.root, "artifact store root")
            _assert_no_symlink_components(staging, "artifact publication directory")
            _assert_latest_directory(latest)
            os.replace(staging, latest)
            staging = None
            committed = True
        except BaseException:
            old_latest_moved = previous_latest_moved or _backup_contains_previous_latest(
                backup, latest
            )
            if (
                old_latest_moved
                and backup is not None
                and staging is not None
                and staging.exists()
                and not latest.exists()
            ):
                _assert_directory(self._store.root, "artifact store root")
                backup = _restore_latest_from_backup(backup, latest)
            _best_effort_remove_private_directory(staging)
            if not old_latest_moved:
                _best_effort_remove_private_directory(backup)
            raise

        if committed:
            _best_effort_remove_private_directory(backup)
            try:
                self._store.retain_latest_runs()
            except OSError:
                pass
        return latest

    @staticmethod
    def _write_text(destination: Path, content: str) -> None:
        _atomic_write(destination, lambda file: file.write(content))


class ProtectedArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        _ensure_directory(self.root, "artifact store root")

    def start_run(self, as_of: datetime) -> ProtectedArtifactRun:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        run_name = _RUN_PREFIX + as_of.astimezone(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        _assert_directory(self.root, "artifact store root")
        path = self.root / run_name
        _ensure_directory(path, "run artifact path")
        for child in path.iterdir():
            if child.is_file() and not child.is_symlink():
                child.unlink()
        return ProtectedArtifactRun(self, path)

    def retain_latest_runs(self) -> None:
        _assert_directory(self.root, "artifact store root")
        run_directories = sorted(
            path
            for path in self.root.iterdir()
            if path.name.startswith(_RUN_PREFIX)
            and path.is_dir()
            and not path.is_symlink()
        )
        for expired in run_directories[:-_RUN_RETENTION]:
            shutil.rmtree(expired)
