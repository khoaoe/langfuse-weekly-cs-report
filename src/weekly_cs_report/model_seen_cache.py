from __future__ import annotations

"""Strict disk contract for cached per-model first-seen timestamps.

Discovering when a model first appeared in Langfuse costs a handful of
`fetch_metrics` calls (see `model_discovery.py`). Once found, the answer never
changes for a given model name, so it is cached here -- the same
tempfile+fsync+replace, 0o600, exact-key-validated idiom as `csat_cache.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
from types import MappingProxyType


_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = {"schema_version", "models"}
_ENTRY_KEYS = {"model", "first_seen", "confirmed", "checked_at"}


class ModelSeenCacheError(RuntimeError):
    """A sanitized cache-contract error."""


@dataclass(frozen=True)
class CachedModelSeen:
    model: str
    first_seen: str | None
    confirmed: bool
    checked_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model:
            raise ModelSeenCacheError("model first-seen entry is invalid")
        if not isinstance(self.confirmed, bool):
            raise ModelSeenCacheError("model first-seen entry is invalid")
        if self.first_seen is not None:
            _parse_utc(self.first_seen)
        _parse_utc(self.checked_at)


@dataclass(frozen=True)
class ModelSeenCache:
    entries: Mapping[str, CachedModelSeen]

    def __post_init__(self) -> None:
        normalized: dict[str, CachedModelSeen] = {}
        for model, entry in self.entries.items():
            if model != entry.model:
                raise ModelSeenCacheError("model first-seen key mismatch")
            normalized[model] = entry
        object.__setattr__(
            self, "entries", MappingProxyType(dict(sorted(normalized.items())))
        )

    def get(self, model: str) -> CachedModelSeen | None:
        return self.entries.get(model)

    def with_entry(self, entry: CachedModelSeen) -> "ModelSeenCache":
        merged = dict(self.entries)
        merged[entry.model] = entry
        return ModelSeenCache(entries=merged)


def load_model_seen_cache(path: Path) -> ModelSeenCache | None:
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise ModelSeenCacheError("model first-seen cache is invalid") from None
    if (
        not stat.S_ISREG(source_status.st_mode)
        or source_status.st_uid != os.geteuid()
        or stat.S_IMODE(source_status.st_mode) != 0o600
    ):
        raise ModelSeenCacheError("model first-seen cache is invalid")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ModelSeenCacheError("model first-seen cache is invalid") from None
    return _cache_from_value(value)


def write_model_seen_cache(path: Path, cache: ModelSeenCache) -> None:
    _atomic_private_json(Path(path), _cache_to_value(cache))


def _cache_from_value(value: object) -> ModelSeenCache:
    if not isinstance(value, Mapping) or set(value) != _CACHE_KEYS:
        raise ModelSeenCacheError("model first-seen cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION:
        raise ModelSeenCacheError("model first-seen cache version is invalid")
    raw_models = value["models"]
    if not isinstance(raw_models, list):
        raise ModelSeenCacheError("model first-seen cache is invalid")
    entries: dict[str, CachedModelSeen] = {}
    for item in raw_models:
        if not isinstance(item, Mapping) or set(item) != _ENTRY_KEYS:
            raise ModelSeenCacheError("model first-seen entry is invalid")
        entry = CachedModelSeen(
            model=item["model"],
            first_seen=item["first_seen"],
            confirmed=item["confirmed"],
            checked_at=item["checked_at"],
        )
        if entry.model in entries:
            raise ModelSeenCacheError("model first-seen identity is duplicated")
        entries[entry.model] = entry
    return ModelSeenCache(entries=entries)


def _cache_to_value(cache: ModelSeenCache) -> dict[str, object]:
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "models": [
            {
                "model": entry.model,
                "first_seen": entry.first_seen,
                "confirmed": entry.confirmed,
                "checked_at": entry.checked_at,
            }
            for entry in cache.entries.values()
        ],
    }


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ModelSeenCacheError("model first-seen timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ModelSeenCacheError("model first-seen timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelSeenCacheError("model first-seen timestamp is invalid")
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
        raise ModelSeenCacheError("model first-seen cache could not be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
