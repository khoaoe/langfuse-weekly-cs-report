from __future__ import annotations

"""Shared private-cache primitives for the Freshdesk job caches.

Every Freshdesk job persists the same envelope -- `{schema_version,
fetched_weeks, records}` -- to a `0600` file under a `0700` runtime directory,
and each one had grown its own copy of the load/write plumbing. The copies had
drifted: of five `_atomic_private_json` implementations two chmod'd the
directory and three only created it when missing, and one
`_validate_utc_timestamp` had lost its `label` argument. This module keeps one
implementation of each, taking the strictest behaviour that was in use.

Callers pass their own error class so a failure still surfaces under the
cache's own sanitized message (`AIReviewCacheError`, `CSATCacheError`, ...)
rather than a shared one that would leak which cache failed.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import stat
import tempfile


_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class DuplicateJSONKey(ValueError):
    """A JSON object repeated a key, which `json` would silently collapse."""


def strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """`object_pairs_hook` that rejects duplicate keys instead of last-wins.

    A cache file with `{"records": [...], "records": []}` would otherwise load
    as the empty list with no error at all.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKey(key)
        result[key] = value
    return result


def is_private_owner_file(details: os.stat_result) -> bool:
    """True when the path is a regular file owned by us and mode `0600`."""
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_uid == os.geteuid()
        and stat.S_IMODE(details.st_mode) == 0o600
    )


def is_private_owner_directory(details: os.stat_result) -> bool:
    """True when the path is a directory owned by us and mode `0700`."""
    return (
        stat.S_ISDIR(details.st_mode)
        and details.st_uid == os.geteuid()
        and stat.S_IMODE(details.st_mode) == 0o700
    )


def validate_monday(
    value: object,
    label: str,
    error: Callable[[str], Exception],
) -> None:
    """Reject anything that is not an ISO date landing on a Monday.

    Cohort weeks are keyed by their Monday, so a non-Monday key means the
    cache was written against a different week definition than the one
    reading it.
    """
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise error(f"{label} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise error(f"{label} is invalid") from None
    if parsed.weekday() != 0:
        raise error(f"{label} is invalid")


def validate_utc_timestamp(
    value: object,
    label: str,
    error: Callable[[str], Exception],
    *,
    require_z_suffix: bool = True,
) -> None:
    """Reject anything that is not a UTC timestamp.

    `require_z_suffix` is the default because every cache but one stores the
    canonical `Z` form. `reconciliation_cache` also accepts an explicit
    `+00:00` offset and has a test pinning that, so it opts out rather than
    having its accepted input silently narrowed here.
    """
    if not isinstance(value, str):
        raise error(f"{label} is invalid")
    if require_z_suffix and not value.endswith("Z"):
        raise error(f"{label} is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise error(f"{label} is invalid") from None
    if parsed.utcoffset() != timedelta(0):
        raise error(f"{label} is invalid")


def atomic_private_json(
    path: Path,
    payload: object,
    error: Callable[[str], Exception],
    message: str,
) -> None:
    """Write `payload` as `0600` JSON, atomically.

    The temporary file is created inside the destination
    directory so `os.replace` is a same-filesystem rename, and the content is
    fsync'd before that rename -- a crash leaves either the old file or the
    new one, never a truncated one.
    """
    directory = path.parent
    # Strictest of the five implementations this replaces, per axis: create the
    # directory `0700`, and when it already exists REJECT it unless it is a
    # private directory we own. `reconciliation_cache` did this; the others
    # chmod'd whatever was there, which silently accepts a parent that was
    # world-readable (or a symlink) at the moment of the write.
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(directory, 0o700)
    except FileExistsError:
        try:
            directory_status = directory.lstat()
        except OSError:
            raise error(message) from None
        if not is_private_owner_directory(directory_status):
            raise error(message)
    except OSError:
        raise error(message) from None

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
        raise error(message) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def read_private_json(
    path: Path,
    error: Callable[[str], Exception],
    message: str,
) -> object | None:
    """Read a `0600` JSON cache, or `None` when it does not exist.

    Opens with `O_NOFOLLOW` and re-checks the mode on the open descriptor,
    then confirms it is the same inode that was stat'd -- a symlink swapped in
    between the two would otherwise redirect the read.
    """
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise error(message) from None
    if not is_private_owner_file(source_status):
        raise error(message)

    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        opened_status = os.fstat(descriptor)
        if (
            not is_private_owner_file(opened_status)
            or source_status.st_dev != opened_status.st_dev
            or source_status.st_ino != opened_status.st_ino
        ):
            raise error(message)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            return json.load(stream, object_pairs_hook=strict_json_object)
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateJSONKey):
        raise error(message) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
