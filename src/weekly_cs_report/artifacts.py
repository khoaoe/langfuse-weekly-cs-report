from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

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


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


class ProtectedArtifactRun:
    def __init__(self, store: ProtectedArtifactStore, path: Path) -> None:
        self._store = store
        self.path = path

    def write_json(self, name: str, payload: object) -> Path:
        _safe_name(name, ".json")
        _assert_safe_keys(payload)
        destination = self.path / name
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

        destination = self.path / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(fieldnames))
                writer.writeheader()
                writer.writerows(rows)
        finally:
            if destination.exists():
                destination.chmod(0o600)
        return destination

    def publish_latest(self) -> Path:
        latest = self._store.root / "latest"
        if latest.exists():
            if not latest.is_dir() or latest.is_symlink():
                raise ArtifactSafetyError("latest artifact path must be a directory")
            for child in latest.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        _ensure_directory(latest)
        for source in sorted(self.path.iterdir()):
            if not source.is_file() or source.is_symlink():
                continue
            destination = latest / source.name
            shutil.copyfile(source, destination)
            destination.chmod(0o600)
        self._store.retain_latest_runs()
        return latest

    @staticmethod
    def _write_text(destination: Path, content: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(content)
        finally:
            if destination.exists():
                destination.chmod(0o600)


class ProtectedArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        _ensure_directory(self.root)

    def start_run(self, as_of: datetime) -> ProtectedArtifactRun:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        run_name = _RUN_PREFIX + as_of.astimezone(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        path = self.root / run_name
        _ensure_directory(path)
        for child in path.iterdir():
            if child.is_file() and not child.is_symlink():
                child.unlink()
        return ProtectedArtifactRun(self, path)

    def retain_latest_runs(self) -> None:
        run_directories = sorted(
            path
            for path in self.root.iterdir()
            if path.name.startswith(_RUN_PREFIX)
            and path.is_dir()
            and not path.is_symlink()
        )
        for expired in run_directories[:-_RUN_RETENTION]:
            shutil.rmtree(expired)
