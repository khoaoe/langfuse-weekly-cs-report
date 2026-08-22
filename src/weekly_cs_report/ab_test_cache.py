from __future__ import annotations

"""Disk persistence for the AB test background snapshot.

Restart survival for the default-window payload, using the same
tempfile+fsync+replace, 0o600 idiom as the other caches in this codebase.
Deliberately its own small store, not a merge into `dashboard_cache.py` /
`SnapshotManager`: `ab_test.py`'s own module docstring establishes that this
layer must stay independent of the weekly snapshot pipeline's enrichment
gate, so persistence for it must not be routed through that governed store.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile


_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = {"schema_version", "generated_at", "arms_key", "payload"}


class AbTestCacheError(RuntimeError):
    """A sanitized cache-contract error."""


@dataclass(frozen=True)
class CachedAbTestSnapshot:
    generated_at: str
    arms_key: str
    payload: dict

    def __post_init__(self) -> None:
        if not isinstance(self.arms_key, str):
            raise AbTestCacheError("AB test cache entry is invalid")
        if not isinstance(self.payload, dict):
            raise AbTestCacheError("AB test cache entry is invalid")
        _parse_utc(self.generated_at)


def load_ab_test_cache(path: Path) -> CachedAbTestSnapshot | None:
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise AbTestCacheError("AB test cache is invalid") from None
    if (
        not stat.S_ISREG(source_status.st_mode)
        or source_status.st_uid != os.geteuid()
        or stat.S_IMODE(source_status.st_mode) != 0o600
    ):
        raise AbTestCacheError("AB test cache is invalid")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AbTestCacheError("AB test cache is invalid") from None
    if not isinstance(value, dict) or set(value) != _CACHE_KEYS:
        raise AbTestCacheError("AB test cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION:
        raise AbTestCacheError("AB test cache version is invalid")
    return CachedAbTestSnapshot(
        generated_at=value["generated_at"],
        arms_key=value["arms_key"],
        payload=value["payload"],
    )


def write_ab_test_cache(path: Path, cache: CachedAbTestSnapshot) -> None:
    payload = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "generated_at": cache.generated_at,
        "arms_key": cache.arms_key,
        "payload": cache.payload,
    }
    _atomic_private_json(Path(path), payload)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise AbTestCacheError("AB test cache timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise AbTestCacheError("AB test cache timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AbTestCacheError("AB test cache timestamp is invalid")
    return parsed.astimezone(timezone.utc)


def _atomic_private_json(path: Path, payload: object) -> None:
    directory = path.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=directory
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError:
        raise AbTestCacheError("AB test cache could not be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
