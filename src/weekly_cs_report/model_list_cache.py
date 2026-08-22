from __future__ import annotations

"""Disk persistence for the background-refreshed recent-model list.

Restart survival for the AB-test model picker's candidate list, using the
same tempfile+fsync+replace, 0o600 idiom as the other caches in this
codebase. `list_recent_models` pages every ticket trace in its lookback
window to stay correctly scoped to `model_core` (see `model_discovery.py`),
which is too expensive to run inline on every request -- this cache is what
lets the picker read an already-computed list instead of blocking on that
scan.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile


_CACHE_SCHEMA_VERSION = 1
_CACHE_KEYS = {"schema_version", "generated_at", "models"}


class ModelListCacheError(RuntimeError):
    """A sanitized cache-contract error."""


@dataclass(frozen=True)
class CachedModelList:
    generated_at: str
    models: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.models, tuple) or not all(
            isinstance(model, str) and model for model in self.models
        ):
            raise ModelListCacheError("recent model list cache entry is invalid")
        _parse_utc(self.generated_at)


def load_model_list_cache(path: Path) -> CachedModelList | None:
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise ModelListCacheError("recent model list cache is invalid") from None
    if (
        not stat.S_ISREG(source_status.st_mode)
        or source_status.st_uid != os.geteuid()
        or stat.S_IMODE(source_status.st_mode) != 0o600
    ):
        raise ModelListCacheError("recent model list cache is invalid")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ModelListCacheError("recent model list cache is invalid") from None
    if not isinstance(value, dict) or set(value) != _CACHE_KEYS:
        raise ModelListCacheError("recent model list cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION:
        raise ModelListCacheError("recent model list cache version is invalid")
    raw_models = value["models"]
    if not isinstance(raw_models, list):
        raise ModelListCacheError("recent model list cache is invalid")
    return CachedModelList(
        generated_at=value["generated_at"], models=tuple(raw_models)
    )


def write_model_list_cache(path: Path, cache: CachedModelList) -> None:
    payload = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "generated_at": cache.generated_at,
        "models": list(cache.models),
    }
    _atomic_private_json(Path(path), payload)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ModelListCacheError("recent model list cache timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ModelListCacheError(
            "recent model list cache timestamp is invalid"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelListCacheError("recent model list cache timestamp is invalid")
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
        raise ModelListCacheError(
            "recent model list cache could not be written"
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
