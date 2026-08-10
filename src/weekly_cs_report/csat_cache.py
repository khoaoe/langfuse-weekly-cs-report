from __future__ import annotations

"""Strict, privacy-safe disk contract for pre-fetched Freshdesk CSAT."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from types import MappingProxyType


_CACHE_SCHEMA_VERSION = 2
_CACHE_KEYS = {"schema_version", "fetched_weeks", "fetch_stats", "responses"}
_STATS_KEYS = {
    "all_response_count",
    "included_bot_response_count",
    "excluded_other_agent_response_count",
    "excluded_null_agent_response_count",
}
_RESPONSE_KEYS = {
    "response_key",
    "ticket_id",
    "survey_id",
    "responded_at",
    "rating_raw",
    "satisfaction_bucket",
    "comment_present",
    "comment_redacted",
}
_RESPONSE_KEY = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BUCKETS = frozenset({"positive", "neutral", "negative"})


class CSATCacheError(RuntimeError):
    """A sanitized cache-contract error."""


@dataclass(frozen=True)
class CachedCSATResponse:
    response_key: str
    ticket_id: str
    survey_id: int
    responded_at: str
    rating_raw: int
    satisfaction_bucket: str
    comment_present: bool
    comment_redacted: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.response_key, str)
            or _RESPONSE_KEY.fullmatch(self.response_key) is None
            or not isinstance(self.ticket_id, str)
            or not self.ticket_id.isdigit()
            or not isinstance(self.survey_id, int)
            or isinstance(self.survey_id, bool)
            or not isinstance(self.rating_raw, int)
            or isinstance(self.rating_raw, bool)
            or self.satisfaction_bucket not in _BUCKETS
            or not isinstance(self.comment_present, bool)
            or (
                self.comment_redacted is not None
                and (
                    not isinstance(self.comment_redacted, str)
                    or not self.comment_redacted.strip()
                    or self.comment_redacted != self.comment_redacted.strip()
                    or len(self.comment_redacted) > 200
                )
            )
            or self.comment_present != (self.comment_redacted is not None)
        ):
            raise CSATCacheError("Freshdesk CSAT cache response is invalid")
        _parse_utc(self.responded_at)


@dataclass(frozen=True)
class CSATCacheStats:
    all_response_count: int
    included_bot_response_count: int
    excluded_other_agent_response_count: int
    excluded_null_agent_response_count: int

    def __post_init__(self) -> None:
        counts = (
            self.all_response_count,
            self.included_bot_response_count,
            self.excluded_other_agent_response_count,
            self.excluded_null_agent_response_count,
        )
        if any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in counts
        ) or self.all_response_count != sum(counts[1:]):
            raise CSATCacheError("Freshdesk CSAT cache stats are invalid")


@dataclass(frozen=True)
class CSATCache:
    fetched_weeks: Mapping[str, str]
    fetch_stats: CSATCacheStats
    responses: tuple[CachedCSATResponse, ...]

    def __post_init__(self) -> None:
        normalized_weeks: dict[str, str] = {}
        for week, fetched_at in self.fetched_weeks.items():
            try:
                date.fromisoformat(week)
            except (TypeError, ValueError):
                raise CSATCacheError("Freshdesk CSAT fetched week is invalid") from None
            _parse_utc(fetched_at)
            normalized_weeks[week] = fetched_at
        normalized_responses = tuple(self.responses)
        keys = [response.response_key for response in normalized_responses]
        if len(keys) != len(set(keys)):
            raise CSATCacheError("Freshdesk CSAT response identity is duplicated")
        object.__setattr__(
            self,
            "fetched_weeks",
            MappingProxyType(dict(sorted(normalized_weeks.items()))),
        )
        object.__setattr__(self, "responses", normalized_responses)

    @property
    def fetched_at(self) -> str | None:
        return max(self.fetched_weeks.values(), default=None)


def load_csat_cache(path: Path) -> CSATCache | None:
    source = Path(path)
    try:
        source_status = source.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise CSATCacheError("Freshdesk CSAT cache is invalid") from None
    if (
        not stat.S_ISREG(source_status.st_mode)
        or source_status.st_uid != os.geteuid()
        or stat.S_IMODE(source_status.st_mode) != 0o600
    ):
        raise CSATCacheError("Freshdesk CSAT cache is invalid")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise CSATCacheError("Freshdesk CSAT cache is invalid") from None
    return _cache_from_value(value)


def write_csat_cache(path: Path, cache: CSATCache) -> None:
    payload = _cache_to_value(cache)
    _atomic_private_json(Path(path), payload)


def _cache_from_value(value: object) -> CSATCache:
    if not isinstance(value, Mapping) or set(value) != _CACHE_KEYS:
        raise CSATCacheError("Freshdesk CSAT cache is invalid")
    if value["schema_version"] != _CACHE_SCHEMA_VERSION:
        raise CSATCacheError("Freshdesk CSAT cache version is invalid")
    raw_weeks = value["fetched_weeks"]
    raw_stats = value["fetch_stats"]
    raw_responses = value["responses"]
    if (
        not isinstance(raw_weeks, Mapping)
        or not isinstance(raw_stats, Mapping)
        or set(raw_stats) != _STATS_KEYS
        or not isinstance(raw_responses, list)
    ):
        raise CSATCacheError("Freshdesk CSAT cache is invalid")
    stats = CSATCacheStats(
        **{key: raw_stats[key] for key in _STATS_KEYS},
    )
    responses: list[CachedCSATResponse] = []
    for item in raw_responses:
        if not isinstance(item, Mapping) or set(item) != _RESPONSE_KEYS:
            raise CSATCacheError("Freshdesk CSAT cache response is invalid")
        responses.append(
            CachedCSATResponse(
                response_key=item["response_key"],
                ticket_id=item["ticket_id"],
                survey_id=item["survey_id"],
                responded_at=item["responded_at"],
                rating_raw=item["rating_raw"],
                satisfaction_bucket=item["satisfaction_bucket"],
                comment_present=item["comment_present"],
                comment_redacted=item["comment_redacted"],
            )
        )
    return CSATCache(
        fetched_weeks={str(key): value for key, value in raw_weeks.items()},
        fetch_stats=stats,
        responses=tuple(responses),
    )


def _cache_to_value(cache: CSATCache) -> dict[str, object]:
    validated = CSATCache(
        fetched_weeks=cache.fetched_weeks,
        fetch_stats=cache.fetch_stats,
        responses=cache.responses,
    )
    return {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "fetched_weeks": dict(validated.fetched_weeks),
        "fetch_stats": {
            key: getattr(validated.fetch_stats, key) for key in sorted(_STATS_KEYS)
        },
        "responses": [
            {
                "response_key": item.response_key,
                "ticket_id": item.ticket_id,
                "survey_id": item.survey_id,
                "responded_at": item.responded_at,
                "rating_raw": item.rating_raw,
                "satisfaction_bucket": item.satisfaction_bucket,
                "comment_present": item.comment_present,
                "comment_redacted": item.comment_redacted,
            }
            for item in validated.responses
        ],
    }


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise CSATCacheError("Freshdesk CSAT timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise CSATCacheError("Freshdesk CSAT timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CSATCacheError("Freshdesk CSAT timestamp is invalid")
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
        raise CSATCacheError("Freshdesk CSAT cache could not be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
