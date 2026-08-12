from __future__ import annotations

"""Freshdesk CSAT discovery and fetch primitives.

This module is imported only by the two CSAT CLI commands.  The dashboard
serving path never imports it and therefore never reads Freshdesk credentials
or performs a Freshdesk request.
"""

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlparse

import httpx

from .csat_cache import (
    CSATCache,
    CSATCacheStats,
    CachedCSATResponse,
)
from .outcome_reconciliation import (
    ConversationMetadata,
    OutcomeReconciliationError,
)
from .freshdesk_entry_coverage import (
    FreshdeskEntryCoverageError,
    FreshdeskTicketMetadata,
)


_CONFIG_KEYS = {
    "schema_version",
    "approved_by",
    "approved_at",
    "bot_agent_ids",
    "survey_scales",
    "notes",
}
_BUCKETS = ("positive", "neutral", "negative")
# Freshdesk's account quota is a rolling window. Eleven bounded five-minute
# waits cover up to 55 minutes without increasing request concurrency.
_MAX_RETRIES = 11
_MAX_RETRY_AFTER_SECONDS = 300.0
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_MAX_CONVERSATION_PAGES = 100
_CONVERSATION_PAGE_SIZE = 100
_RECENT_WEEK_REFETCH_INTERVAL = timedelta(hours=6)
_APPROVED_FRESHDESK_HOST = "vngzalopay.freshdesk.com"
_REDACTED = "[đã ẩn]"
_EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+", re.IGNORECASE)
_SPACED_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?84|0)(?:[\s._-]*\d){8,10}(?!\d)"
)
_LONG_NUMBER_PATTERN = re.compile(r"(?<!\d)(?:\d[\s._-]*){6,}(?!\d)")
_TRANSACTION_TOKEN_PATTERN = re.compile(
    r"\b(?=[A-Za-z0-9_-]{8,}\b)(?=[A-Za-z0-9_-]*[A-Za-z])"
    r"(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+\b"
)


class FreshdeskCSATError(RuntimeError):
    """A sanitized failure safe to print from the command-line boundary."""


class FreshdeskFetchDeadline(FreshdeskCSATError):
    """The bounded Freshdesk job must resume from its private checkpoint."""


class FreshdeskRateLimitExhausted(FreshdeskCSATError):
    """The current run must stop; its last private checkpoint remains usable."""


class FreshdeskCookieMissing(FreshdeskCSATError):
    """No Freshdesk cookie is configured; the caller must supply one."""


class FreshdeskCookieExpired(FreshdeskCSATError):
    """The configured Freshdesk cookie was rejected by the UI API (401/403)."""


class _FreshdeskHTTPError(FreshdeskCSATError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class _FetchDurationReached(RuntimeError):
    """Internal control flow; never crosses the CLI boundary."""


@dataclass(frozen=True)
class FreshdeskSettings:
    base_url: str
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        try:
            port = parsed.port
        except ValueError:
            raise FreshdeskCSATError("Freshdesk settings are invalid") from None
        if (
            parsed.scheme != "https"
            or parsed.hostname != _APPROVED_FRESHDESK_HOST
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
            or not self.api_key
        ):
            raise FreshdeskCSATError("Freshdesk settings are invalid")
        object.__setattr__(self, "base_url", f"https://{parsed.netloc}".rstrip("/"))


_COOKIE_FILENAME = "freshdesk_cookie"
_COOKIE_STATE_FILENAME = "freshdesk_cookie_state.json"
_COOKIE_STATES = frozenset({"ok", "expired", "missing"})
_COOKIE_STATE_KEYS = frozenset(
    {"schema_version", "updated_at", "last_verified_at", "last_failure_at", "state"}
)


def cookie_path(runtime_directory: Path) -> Path:
    return Path(runtime_directory) / _COOKIE_FILENAME


def cookie_state_path(runtime_directory: Path) -> Path:
    return Path(runtime_directory) / _COOKIE_STATE_FILENAME


def load_freshdesk_cookie(runtime_directory: Path) -> str:
    """Read the persisted cookie; the file wins over the bootstrap env var."""
    path = cookie_path(runtime_directory)
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    env_value = os.environ.get("FRESHDESK_COOKIE", "").strip()
    if env_value:
        return env_value
    raise FreshdeskCookieMissing("Freshdesk cookie is not configured")


def write_freshdesk_cookie(runtime_directory: Path, cookie: str) -> None:
    if not isinstance(cookie, str) or not cookie.strip():
        raise FreshdeskCSATError("Freshdesk cookie value is invalid")
    path = cookie_path(runtime_directory)
    parent = path.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise FreshdeskCSATError(
            "Freshdesk private file could not be written"
        ) from None
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=parent,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(cookie.strip())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError:
        raise FreshdeskCSATError(
            "Freshdesk private file could not be written"
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def read_cookie_state(runtime_directory: Path) -> dict[str, object]:
    """Never raises for a missing file -- returns the synthetic 'missing' state."""
    path = cookie_state_path(runtime_directory)
    if not path.exists():
        return {
            "schema_version": 1,
            "updated_at": None,
            "last_verified_at": None,
            "last_failure_at": None,
            "state": "missing",
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise FreshdeskCSATError("Freshdesk cookie state is invalid") from None
    if (
        not isinstance(value, Mapping)
        or set(value) != _COOKIE_STATE_KEYS
        or value["schema_version"] != 1
        or value["state"] not in _COOKIE_STATES
    ):
        raise FreshdeskCSATError("Freshdesk cookie state is invalid")
    return dict(value)


def _write_cookie_state(
    runtime_directory: Path,
    *,
    state: str,
    last_verified_at: str | None = None,
    last_failure_at: str | None = None,
) -> None:
    if state not in _COOKIE_STATES:
        raise FreshdeskCSATError("Freshdesk cookie state is invalid")
    current = read_cookie_state(runtime_directory)
    payload = {
        "schema_version": 1,
        "updated_at": _format_utc(datetime.now(timezone.utc)),
        "last_verified_at": (
            last_verified_at
            if last_verified_at is not None
            else current.get("last_verified_at")
        ),
        "last_failure_at": (
            last_failure_at
            if last_failure_at is not None
            else current.get("last_failure_at")
        ),
        "state": state,
    }
    _atomic_private_json(cookie_state_path(runtime_directory), payload)


def mark_cookie_verified(runtime_directory: Path) -> None:
    now = _format_utc(datetime.now(timezone.utc))
    _write_cookie_state(runtime_directory, state="ok", last_verified_at=now)


def mark_cookie_expired(runtime_directory: Path) -> None:
    now = _format_utc(datetime.now(timezone.utc))
    _write_cookie_state(runtime_directory, state="expired", last_failure_at=now)


@dataclass(frozen=True)
class CSATResponse:
    response_key: str
    ticket_id: str
    survey_id: int
    responded_at: str
    rating_raw: int
    satisfaction_bucket: str
    comment_present: bool
    comment_redacted: str | None


@dataclass(frozen=True)
class CSATFetchStats:
    all_response_count: int = 0
    included_bot_response_count: int = 0
    excluded_other_agent_response_count: int = 0
    excluded_null_agent_response_count: int = 0


@dataclass(frozen=True)
class CSATFetchResult:
    responses: tuple[CSATResponse, ...]
    stats: CSATFetchStats


@dataclass(frozen=True)
class IncrementalCSATResult:
    cache: CSATCache
    completed_weeks: tuple[str, ...]
    complete: bool


class FreshdeskClient:
    """Small GET-only client with bounded 429 retries and sanitized errors."""

    def __init__(
        self,
        settings: FreshdeskSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=settings.base_url,
            auth=httpx.BasicAuth(settings.api_key, "X"),
            headers={"Accept": "application/json"},
            timeout=30.0,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> FreshdeskClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_ticket_fields(self) -> object:
        return self._get_json("/api/v2/ticket_fields")

    def get_satisfaction_ratings(self, ticket_id: str) -> tuple[object, ...]:
        if not ticket_id.isdigit():
            raise FreshdeskCSATError("Freshdesk ticket ID is invalid")
        value = self._get_json(
            f"/api/v2/tickets/{ticket_id}/satisfaction_ratings",
            not_found=(),
        )
        if not isinstance(value, (list, tuple)):
            raise FreshdeskCSATError("Freshdesk rating response is invalid")
        return tuple(value)

    def get_conversation_metadata(
        self,
        ticket_id: str,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[ConversationMetadata, ...]:
        """Fetch conversations while retaining only the six approved fields."""

        if not ticket_id.isdigit():
            raise FreshdeskCSATError("Freshdesk ticket ID is invalid")
        projected: list[ConversationMetadata] = []
        for page in range(1, _MAX_CONVERSATION_PAGES + 1):
            value = self._get_json(
                f"/api/v2/tickets/{ticket_id}/conversations",
                params={"page": page, "per_page": _CONVERSATION_PAGE_SIZE},
                not_found=(),
                should_stop=should_stop,
            )
            if not isinstance(value, (list, tuple)):
                raise FreshdeskCSATError(
                    "Freshdesk conversation response is invalid"
                )
            try:
                rows = tuple(
                    ConversationMetadata(
                        conversation_id=item.get("id"),
                        author_id=item.get("user_id"),
                        incoming=item.get("incoming"),
                        private=item.get("private"),
                        source=item.get("source"),
                        created_at=item.get("created_at"),
                        category=item.get("category"),
                        is_autorep_private_note=(
                            item.get("private") is True
                            and _contains_autorep_marker(
                                item.get("body_text") or item.get("body")
                            )
                        ),
                    )
                    for item in value
                    if isinstance(item, Mapping)
                )
            except (OutcomeReconciliationError, TypeError):
                raise FreshdeskCSATError(
                    "Freshdesk conversation response is invalid"
                ) from None
            if len(rows) != len(value):
                raise FreshdeskCSATError(
                    "Freshdesk conversation response is invalid"
                )
            projected.extend(rows)
            if len(value) < _CONVERSATION_PAGE_SIZE:
                return tuple(projected)
        raise FreshdeskCSATError("Freshdesk conversation page limit exceeded")

    def list_ticket_metadata(
        self,
        *,
        updated_since: datetime,
        max_pages: int = 300,
        page_size: int = 50,
        start_page: int = 1,
        existing: tuple[FreshdeskTicketMetadata, ...] = (),
        on_page: Callable[[tuple[FreshdeskTicketMetadata, ...], int, bool], None]
        | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[FreshdeskTicketMetadata, ...]:
        """List Freshdesk tickets and project only the join-safe metadata."""

        if (
            updated_since.tzinfo is None
            or updated_since.utcoffset() is None
            or max_pages < 1
            or max_pages > 300
            or page_size != 50
            or start_page < 1
            or start_page > max_pages + 1
            or any(not isinstance(item, FreshdeskTicketMetadata) for item in existing)
        ):
            raise FreshdeskCSATError("Freshdesk ticket listing options are invalid")
        updated_since_utc = updated_since.astimezone(timezone.utc)
        projected: list[FreshdeskTicketMetadata] = list(existing)
        seen_ids: set[str] = {item.ticket_id for item in projected}
        if len(seen_ids) != len(projected):
            raise FreshdeskCSATError("Freshdesk ticket response contains duplicate tickets")
        page = start_page
        while page <= max_pages:
            _check_fetch_deadline(should_stop)
            value = self._get_json(
                "/api/v2/tickets",
                params={
                    "updated_since": _format_utc(updated_since_utc),
                    # The lower bound is updated_since, so sort by the same
                    # indexed field. Sorting by created_at makes deep pages
                    # materially more likely to fail on the Freshdesk tenant.
                    "order_by": "updated_at",
                    "order_type": "asc",
                    "page": page,
                    "per_page": page_size,
                },
                should_stop=should_stop,
            )
            if not isinstance(value, list):
                raise FreshdeskCSATError("Freshdesk ticket response is invalid")
            page_rows: list[FreshdeskTicketMetadata] = []
            for item in value:
                if not isinstance(item, Mapping):
                    raise FreshdeskCSATError("Freshdesk ticket response is invalid")
                try:
                    row = FreshdeskTicketMetadata(
                        ticket_id=str(item["id"]),
                        created_at=item["created_at"],
                    )
                except (KeyError, TypeError, FreshdeskEntryCoverageError):
                    raise FreshdeskCSATError(
                        "Freshdesk ticket response is invalid"
                    ) from None
                if row.ticket_id in seen_ids:
                    raise FreshdeskCSATError(
                        "Freshdesk ticket response contains duplicate tickets"
                    )
                seen_ids.add(row.ticket_id)
                page_rows.append(row)
            projected.extend(page_rows)
            is_complete = len(value) < page_size
            if on_page is not None:
                on_page(tuple(projected), page + 1, is_complete)
            _check_fetch_deadline(should_stop)
            if is_complete:
                return tuple(projected)
            page += 1
        raise FreshdeskCSATError("Freshdesk ticket page limit exceeded")

    def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        not_found: object | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> object:
        for attempt in range(_MAX_RETRIES + 1):
            _check_fetch_deadline(should_stop)
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError:
                raise FreshdeskCSATError("Freshdesk request failed") from None
            if response.is_redirect:
                raise FreshdeskCSATError("Freshdesk redirect was rejected")
            if response.status_code == 404 and not_found is not None:
                return not_found
            if response.status_code == 429 and attempt < _MAX_RETRIES:
                delay = _retry_after(response.headers.get("Retry-After"))
                if should_stop is not None and should_stop():
                    raise FreshdeskFetchDeadline("Freshdesk fetch duration limit reached")
                self._sleep(delay)
                _check_fetch_deadline(should_stop)
                continue
            if response.status_code in {401, 403}:
                raise _FreshdeskHTTPError(
                    response.status_code,
                    "Freshdesk authentication or permission failed"
                )
            if not 200 <= response.status_code < 300:
                raise _FreshdeskHTTPError(
                    response.status_code,
                    f"Freshdesk request failed with status {response.status_code}",
                )
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise FreshdeskCSATError("Freshdesk response exceeded the byte limit")
            try:
                return response.json()
            except ValueError:
                raise FreshdeskCSATError("Freshdesk returned invalid JSON") from None
        raise FreshdeskRateLimitExhausted(
            "Freshdesk rate limit retry budget was exhausted"
        )


class FreshdeskUIClient:
    """Small GET-only client for Freshdesk's internal UI API (/api/_/...),
    cookie-authenticated. Mirrors the two FreshdeskClient methods that
    fetch_csat_population() needs so callers can swap transports without
    changing call sites. Confirmed live (2026-08-12 probe, ticket 7005238)
    to return the identical JSON shape as the REST v2 equivalents. Does not
    consume REST API quota and is not subject to its rolling-window limit.
    """

    def __init__(
        self,
        cookie: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(cookie, str) or not cookie.strip():
            raise FreshdeskCSATError("Freshdesk cookie is invalid")
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=f"https://{_APPROVED_FRESHDESK_HOST}",
            headers={
                "Cookie": cookie.strip(),
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=30.0,
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> FreshdeskUIClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_satisfaction_ratings(self, ticket_id: str) -> tuple[object, ...]:
        if not ticket_id.isdigit():
            raise FreshdeskCSATError("Freshdesk ticket ID is invalid")
        value = self._get_json(
            f"/api/_/tickets/{ticket_id}/satisfaction_ratings",
            not_found=(),
        )
        if isinstance(value, Mapping):
            value = value.get("satisfaction_ratings")
        if not isinstance(value, (list, tuple)):
            raise FreshdeskCSATError("Freshdesk rating response is invalid")
        return tuple(value)

    def get_conversation_metadata(
        self,
        ticket_id: str,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[ConversationMetadata, ...]:
        """Fetch conversations while retaining only the six approved fields.

        The UI API returns the full conversation list in one response (no
        page parameter observed in the 2026-08-12 probe), tagged with a
        meta.count. Fail closed rather than guess at pagination mechanics
        if the returned count ever disagrees with the reported total.
        """

        if not ticket_id.isdigit():
            raise FreshdeskCSATError("Freshdesk ticket ID is invalid")
        raw = self._get_json(
            f"/api/_/tickets/{ticket_id}/conversations",
            not_found=(),
            should_stop=should_stop,
        )
        if not isinstance(raw, Mapping):
            raise FreshdeskCSATError("Freshdesk conversation response is invalid")
        value = raw.get("conversations")
        if not isinstance(value, (list, tuple)):
            raise FreshdeskCSATError("Freshdesk conversation response is invalid")
        meta = raw.get("meta")
        reported_count = meta.get("count") if isinstance(meta, Mapping) else None
        if (
            isinstance(reported_count, int)
            and not isinstance(reported_count, bool)
            and reported_count != len(value)
        ):
            raise FreshdeskCSATError("Freshdesk conversation response is incomplete")
        try:
            rows = tuple(
                ConversationMetadata(
                    conversation_id=item.get("id"),
                    author_id=item.get("user_id"),
                    incoming=item.get("incoming"),
                    private=item.get("private"),
                    source=item.get("source"),
                    created_at=item.get("created_at"),
                    category=item.get("category"),
                    is_autorep_private_note=(
                        item.get("private") is True
                        and _contains_autorep_marker(
                            item.get("body_text") or item.get("body")
                        )
                    ),
                )
                for item in value
                if isinstance(item, Mapping)
            )
        except (OutcomeReconciliationError, TypeError):
            raise FreshdeskCSATError(
                "Freshdesk conversation response is invalid"
            ) from None
        if len(rows) != len(value):
            raise FreshdeskCSATError("Freshdesk conversation response is invalid")
        return rows

    def verify(self) -> None:
        """Cheapest possible live check that the cookie still authenticates.

        Raises FreshdeskCookieExpired on 401/403. Used by the web layer's
        cookie-update endpoint (spec 2026-08-12 SS6.3) -- exactly one such
        request is allowed there; it must never fetch ticket data.
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=1)
        self._get_json(
            "/api/_/tickets",
            params=[
                ("only", "count"),
                ("query_hash[0][condition]", "created_at"),
                ("query_hash[0][operator]", "is_greater_than"),
                ("query_hash[0][type]", "default"),
                ("query_hash[0][value][from]", since.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
                ("query_hash[0][value][to]", now.strftime("%Y-%m-%dT%H:%M:%S.999Z")),
            ],
        )

    def list_ticket_metadata(
        self,
        *,
        updated_since: datetime,
        max_pages: int = 300,
        page_size: int = 50,
        start_page: int = 1,
        existing: tuple[FreshdeskTicketMetadata, ...] = (),
        on_page: Callable[[tuple[FreshdeskTicketMetadata, ...], int, bool], None]
        | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[FreshdeskTicketMetadata, ...]:
        """List tickets via the UI API, filtered by created_at >= updated_since.

        The UI API's query_hash rejects an updated_at condition (confirmed
        400 invalid_value in the 2026-08-12 probe) -- only created_at works.
        This is not a behavior loss for any current caller: every existing
        caller of the REST equivalent immediately re-filters its result to
        created_at >= updated_since anyway (entry coverage narrows to
        filtered_inventory before use), so a ticket created before the
        window would be fetched by REST and then discarded downstream.
        Filtering by created_at here produces the identical final population,
        just without the wasted fetch.
        """
        if (
            updated_since.tzinfo is None
            or updated_since.utcoffset() is None
            or max_pages < 1
            or max_pages > 300
            or page_size != 50
            or start_page < 1
            or start_page > max_pages + 1
            or any(
                not isinstance(item, FreshdeskTicketMetadata) for item in existing
            )
        ):
            raise FreshdeskCSATError("Freshdesk ticket listing options are invalid")
        updated_since_utc = updated_since.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        projected: list[FreshdeskTicketMetadata] = list(existing)
        seen_ids: set[str] = {item.ticket_id for item in projected}
        if len(seen_ids) != len(projected):
            raise FreshdeskCSATError(
                "Freshdesk ticket response contains duplicate tickets"
            )
        query_hash_params = [
            ("query_hash[0][condition]", "created_at"),
            ("query_hash[0][operator]", "is_greater_than"),
            ("query_hash[0][type]", "default"),
            (
                "query_hash[0][value][from]",
                updated_since_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            ),
            ("query_hash[0][value][to]", now.strftime("%Y-%m-%dT%H:%M:%S.999Z")),
        ]
        page = start_page
        while page <= max_pages:
            _check_fetch_deadline(should_stop)
            value = self._get_json(
                "/api/_/tickets",
                params=[
                    ("order_by", "created_at"),
                    ("order_type", "asc"),
                    ("page", page),
                    ("per_page", page_size),
                ]
                + query_hash_params,
                should_stop=should_stop,
            )
            if not isinstance(value, Mapping):
                raise FreshdeskCSATError("Freshdesk ticket response is invalid")
            tickets = value.get("tickets")
            if not isinstance(tickets, list):
                raise FreshdeskCSATError("Freshdesk ticket response is invalid")
            page_rows: list[FreshdeskTicketMetadata] = []
            for item in tickets:
                if not isinstance(item, Mapping):
                    raise FreshdeskCSATError("Freshdesk ticket response is invalid")
                try:
                    row = FreshdeskTicketMetadata(
                        ticket_id=str(item["id"]),
                        created_at=item["created_at"],
                    )
                except (KeyError, TypeError, FreshdeskEntryCoverageError):
                    raise FreshdeskCSATError(
                        "Freshdesk ticket response is invalid"
                    ) from None
                if row.ticket_id in seen_ids:
                    raise FreshdeskCSATError(
                        "Freshdesk ticket response contains duplicate tickets"
                    )
                seen_ids.add(row.ticket_id)
                page_rows.append(row)
            projected.extend(page_rows)
            is_complete = len(tickets) < page_size
            if on_page is not None:
                on_page(tuple(projected), page + 1, is_complete)
            _check_fetch_deadline(should_stop)
            if is_complete:
                return tuple(projected)
            page += 1
            self._sleep(0.1)
        raise FreshdeskCSATError("Freshdesk ticket page limit exceeded")

    def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        not_found: object | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> object:
        for attempt in range(_MAX_RETRIES + 1):
            _check_fetch_deadline(should_stop)
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError:
                raise FreshdeskCSATError("Freshdesk request failed") from None
            if response.is_redirect:
                raise FreshdeskCSATError("Freshdesk redirect was rejected")
            if response.status_code == 404 and not_found is not None:
                return not_found
            if response.status_code == 429 and attempt < _MAX_RETRIES:
                delay = _retry_after(response.headers.get("Retry-After"))
                if should_stop is not None and should_stop():
                    raise FreshdeskFetchDeadline("Freshdesk fetch duration limit reached")
                self._sleep(delay)
                _check_fetch_deadline(should_stop)
                continue
            if response.status_code in {401, 403}:
                raise FreshdeskCookieExpired("Freshdesk cookie was rejected")
            if not 200 <= response.status_code < 300:
                raise _FreshdeskHTTPError(
                    response.status_code,
                    f"Freshdesk request failed with status {response.status_code}",
                )
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise FreshdeskCSATError("Freshdesk response exceeded the byte limit")
            try:
                return response.json()
            except ValueError:
                raise FreshdeskCSATError("Freshdesk returned invalid JSON") from None
        raise FreshdeskRateLimitExhausted(
            "Freshdesk rate limit retry budget was exhausted"
        )


def collect_ticket_ratings(
    client: FreshdeskClient,
    ticket_ids: Sequence[str],
    config: FreshdeskAgentConfig,
) -> CSATFetchResult:
    responses: list[CSATResponse] = []
    all_count = 0
    included_count = 0
    other_count = 0
    null_count = 0
    seen_keys: set[str] = set()
    for ticket_id in ticket_ids:
        normalized_ticket_id = str(ticket_id)
        ratings = client.get_satisfaction_ratings(normalized_ticket_id)
        conversations: tuple[ConversationMetadata, ...] | None = None
        for value in ratings:
            if not isinstance(value, Mapping):
                raise FreshdeskCSATError("Freshdesk rating response is invalid")
            all_count += 1
            agent_id = value.get("agent_id")
            if agent_id is not None and (
                not isinstance(agent_id, int)
                or isinstance(agent_id, bool)
                or agent_id not in config.bot_agent_ids
            ):
                other_count += 1
                continue
            if agent_id is None:
                if conversations is None:
                    conversations = client.get_conversation_metadata(
                        normalized_ticket_id
                    )
                if not _survey_follows_bot_response(
                    value,
                    conversations,
                    config.bot_agent_ids,
                ):
                    null_count += 1
                    continue
            elif conversations is None:
                get_conversations = getattr(
                    client,
                    "get_conversation_metadata",
                    None,
                )
                if callable(get_conversations):
                    conversations = get_conversations(normalized_ticket_id)
            if (
                conversations is not None
                and _survey_has_autorep_note(value, conversations)
            ):
                other_count += 1
                continue
            response = _bot_response(value, normalized_ticket_id, config)
            if response.response_key in seen_keys:
                raise FreshdeskCSATError("Freshdesk response identity is duplicated")
            seen_keys.add(response.response_key)
            responses.append(response)
            included_count += 1
    return CSATFetchResult(
        responses=tuple(responses),
        stats=CSATFetchStats(
            all_response_count=all_count,
            included_bot_response_count=included_count,
            excluded_other_agent_response_count=other_count,
            excluded_null_agent_response_count=null_count,
        ),
    )


def _survey_follows_bot_response(
    value: Mapping[str, object],
    conversations: tuple[ConversationMetadata, ...],
    bot_agent_ids: frozenset[int],
) -> bool:
    """Associate a null-agent survey with its immediately preceding reply."""

    created_at = value.get("created_at")
    if not isinstance(created_at, str):
        raise FreshdeskCSATError("Freshdesk bot rating is invalid")
    survey_time = _utc_iso(created_at)
    latest = _latest_public_outgoing_before(value, conversations)
    if latest is None or latest.author_id not in bot_agent_ids:
        return False
    return not _survey_has_autorep_note(value, conversations, latest=latest)


def _survey_has_autorep_note(
    value: Mapping[str, object],
    conversations: tuple[ConversationMetadata, ...],
    *,
    latest: ConversationMetadata | None = None,
) -> bool:
    created_at = value.get("created_at")
    if not isinstance(created_at, str):
        raise FreshdeskCSATError("Freshdesk bot rating is invalid")
    survey_time = _utc_iso(created_at)
    latest_response = latest or _latest_public_outgoing_before(
        value,
        conversations,
    )
    if latest_response is None:
        return False
    latest_time = _utc_iso(latest_response.created_at)
    return any(
        conversation.is_autorep_private_note
        and latest_time < _utc_iso(conversation.created_at) < survey_time
        for conversation in conversations
    )


def _latest_public_outgoing_before(
    value: Mapping[str, object],
    conversations: tuple[ConversationMetadata, ...],
) -> ConversationMetadata | None:
    created_at = value.get("created_at")
    if not isinstance(created_at, str):
        raise FreshdeskCSATError("Freshdesk bot rating is invalid")
    survey_time = _utc_iso(created_at)
    preceding = [
        conversation
        for conversation in conversations
        if (
            not conversation.incoming
            and not conversation.private
            and conversation.source != 6
            and _utc_iso(conversation.created_at) < survey_time
        )
    ]
    if not preceding:
        return None
    return max(
        preceding,
        key=lambda conversation: (
            _utc_iso(conversation.created_at),
            conversation.conversation_id,
        ),
    )


def _contains_autorep_marker(value: object) -> bool:
    return isinstance(value, str) and "autorep" in value.casefold()


def redact_survey_comment(value: object) -> str | None:
    """Redact customer-entered text in memory before any persistence."""
    if not isinstance(value, str) or not value.strip():
        return None
    from .dashboard_schema import (
        _COMMENT_URL,
        _VIETNAMESE_FAMILY_NAMES,
        _VIETNAMESE_NAME_MIDDLES,
        _safe_string,
    )

    cleaned = value.strip()
    for pattern in (
        _EMAIL_PATTERN,
        _COMMENT_URL,
        _SPACED_PHONE_PATTERN,
        _LONG_NUMBER_PATTERN,
        _TRANSACTION_TOKEN_PATTERN,
    ):
        cleaned = pattern.sub(_REDACTED, cleaned)
    words = cleaned.split()
    redacted_words: list[str] = []
    index = 0
    while index < len(words):
        token = words[index].strip(".,:;!?()[]{}\"'")
        folded = token.casefold()
        previous_folded = (
            words[index - 1].strip(".,:;!?()[]{}\"'").casefold()
            if index > 0
            else None
        )
        next_folded = (
            words[index + 1].strip(".,:;!?()[]{}\"'").casefold()
            if index + 1 < len(words)
            else None
        )
        is_common_phrase = (folded, next_folded) in {
            ("lý", "do"),
            ("ly", "do"),
            ("hồ", "sơ"),
            ("ho", "so"),
        }
        is_xu_ly_phrase = folded in {"lý", "ly"} and previous_folded in {
            "xử",
            "xu",
        }
        is_ambiguous_lower_ascii = (
            folded in {"do", "ho", "le", "ly", "vo", "vu", "dang"}
            and not token[:1].isupper()
            and next_folded not in _VIETNAMESE_NAME_MIDDLES
        )
        if (
            folded in _VIETNAMESE_FAMILY_NAMES
            and not is_xu_ly_phrase
            and not is_common_phrase
            and not is_ambiguous_lower_ascii
            and index + 1 < len(words)
        ):
            end = index + 2
            if next_folded in _VIETNAMESE_NAME_MIDDLES and index + 2 < len(words):
                end = index + 3
            redacted_words.append(_REDACTED)
            index = end
            continue
        redacted_words.append(words[index])
        index += 1
    candidate = " ".join(redacted_words)[:200].strip()
    if not candidate:
        return None
    try:
        _safe_string(candidate, "comment_redacted")
    except ValueError:
        return _REDACTED
    return candidate


def fetch_csat_population(
    client: FreshdeskClient,
    population: Mapping[str, Sequence[str]],
    config: FreshdeskAgentConfig,
    *,
    existing: CSATCache | None,
    as_of: datetime,
    since_week: date | None = None,
    max_workers: int = 2,
    max_duration_seconds: float = 30 * 60,
    monotonic: Callable[[], float] = time.monotonic,
    on_week_complete: Callable[[CSATCache], None] | None = None,
) -> IncrementalCSATResult:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise FreshdeskCSATError("CSAT fetch as-of must include a timezone")
    if max_workers < 1 or max_workers > 8 or max_duration_seconds <= 0:
        raise FreshdeskCSATError("CSAT fetch options are invalid")
    base = existing or CSATCache(
        fetched_weeks={},
        fetch_stats=CSATCacheStats(0, 0, 0, 0),
        responses=(),
    )
    normalized_population = _normalize_population(population, since_week=since_week)
    target_weeks = tuple(
        week
        for week in sorted(normalized_population)
        if _week_needs_fetch(week, base.fetched_weeks, as_of)
    )
    started_at = monotonic()
    fetched_weeks = dict(base.fetched_weeks)
    responses_by_key = {
        response.response_key: response for response in base.responses
    }
    completed: list[str] = []
    aggregate_stats = CSATFetchStats()
    for week in target_weeks:
        if monotonic() - started_at >= max_duration_seconds:
            return IncrementalCSATResult(
                cache=_build_cache(fetched_weeks, responses_by_key, aggregate_stats, base),
                completed_weeks=tuple(completed),
                complete=False,
            )
        ticket_ids = normalized_population[week]
        try:
            week_result = _fetch_week(
                client,
                ticket_ids,
                config,
                max_workers=max_workers,
                should_stop=lambda: (
                    monotonic() - started_at >= max_duration_seconds
                ),
            )
        except _FetchDurationReached:
            return IncrementalCSATResult(
                cache=_build_cache(
                    fetched_weeks,
                    responses_by_key,
                    aggregate_stats,
                    base,
                ),
                completed_weeks=tuple(completed),
                complete=False,
            )
        fetched_ticket_ids = frozenset(ticket_ids)
        responses_by_key = {
            key: response
            for key, response in responses_by_key.items()
            if response.ticket_id not in fetched_ticket_ids
        }
        for response in week_result.responses:
            cached = CachedCSATResponse(
                response_key=response.response_key,
                ticket_id=response.ticket_id,
                survey_id=response.survey_id,
                responded_at=response.responded_at,
                rating_raw=response.rating_raw,
                satisfaction_bucket=response.satisfaction_bucket,
                comment_present=response.comment_present,
                comment_redacted=response.comment_redacted,
            )
            if cached.response_key in responses_by_key:
                raise FreshdeskCSATError("Freshdesk response identity is duplicated")
            responses_by_key[cached.response_key] = cached
        aggregate_stats = _add_stats(aggregate_stats, week_result.stats)
        fetched_weeks[week] = _format_utc(as_of)
        completed.append(week)
        if on_week_complete is not None:
            on_week_complete(
                _build_cache(
                    fetched_weeks,
                    responses_by_key,
                    aggregate_stats,
                    base,
                )
            )
    return IncrementalCSATResult(
        cache=_build_cache(fetched_weeks, responses_by_key, aggregate_stats, base),
        completed_weeks=tuple(completed),
        complete=True,
    )


def _fetch_week(
    client: FreshdeskClient,
    ticket_ids: tuple[str, ...],
    config: FreshdeskAgentConfig,
    *,
    max_workers: int,
    should_stop: Callable[[], bool],
) -> CSATFetchResult:
    results: list[CSATFetchResult] = []
    if max_workers == 1:
        for ticket_id in ticket_ids:
            if should_stop():
                raise _FetchDurationReached
            results.append(collect_ticket_ratings(client, (ticket_id,), config))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for start in range(0, len(ticket_ids), max_workers):
                if should_stop():
                    raise _FetchDurationReached
                batch = ticket_ids[start : start + max_workers]
                futures = tuple(
                    executor.submit(
                        collect_ticket_ratings,
                        client,
                        (ticket_id,),
                        config,
                    )
                    for ticket_id in batch
                )
                results.extend(future.result() for future in futures)
    responses = tuple(
        response for result in results for response in result.responses
    )
    stats = CSATFetchStats()
    for result in results:
        stats = _add_stats(stats, result.stats)
    return CSATFetchResult(responses=responses, stats=stats)


def _normalize_population(
    population: Mapping[str, Sequence[str]],
    *,
    since_week: date | None,
) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for raw_week, raw_ticket_ids in population.items():
        try:
            week = date.fromisoformat(raw_week)
        except (TypeError, ValueError):
            raise FreshdeskCSATError("CSAT population week is invalid") from None
        if week.weekday() != 0 or (since_week is not None and week < since_week):
            continue
        ticket_ids = tuple(sorted({str(ticket_id) for ticket_id in raw_ticket_ids}))
        if any(not ticket_id.isdigit() for ticket_id in ticket_ids):
            raise FreshdeskCSATError("CSAT population ticket is invalid")
        if seen.intersection(ticket_ids):
            raise FreshdeskCSATError("CSAT population contains duplicate tickets")
        seen.update(ticket_ids)
        normalized[raw_week] = ticket_ids
    return dict(sorted(normalized.items()))


def _week_needs_fetch(
    week: str,
    fetched_weeks: Mapping[str, str],
    as_of: datetime,
) -> bool:
    fetched_at = fetched_weeks.get(week)
    if fetched_at is None:
        return True
    week_end = date.fromisoformat(week) + timedelta(days=6)
    if as_of.date() > week_end + timedelta(days=14):
        return False
    normalized = fetched_at[:-1] + "+00:00" if fetched_at.endswith("Z") else fetched_at
    cached_at = datetime.fromisoformat(normalized)
    return (
        as_of.astimezone(timezone.utc) - cached_at.astimezone(timezone.utc)
        >= _RECENT_WEEK_REFETCH_INTERVAL
    )


def _add_stats(left: CSATFetchStats, right: CSATFetchStats) -> CSATFetchStats:
    return CSATFetchStats(
        all_response_count=left.all_response_count + right.all_response_count,
        included_bot_response_count=(
            left.included_bot_response_count + right.included_bot_response_count
        ),
        excluded_other_agent_response_count=(
            left.excluded_other_agent_response_count
            + right.excluded_other_agent_response_count
        ),
        excluded_null_agent_response_count=(
            left.excluded_null_agent_response_count
            + right.excluded_null_agent_response_count
        ),
    )


def _build_cache(
    fetched_weeks: Mapping[str, str],
    responses_by_key: Mapping[str, CachedCSATResponse],
    stats: CSATFetchStats,
    base: CSATCache,
) -> CSATCache:
    selected_stats = (
        CSATCacheStats(
            stats.all_response_count,
            stats.included_bot_response_count,
            stats.excluded_other_agent_response_count,
            stats.excluded_null_agent_response_count,
        )
        if stats.all_response_count > 0
        else base.fetch_stats
    )
    return CSATCache(
        fetched_weeks=fetched_weeks,
        fetch_stats=selected_stats,
        responses=tuple(
            response for _, response in sorted(responses_by_key.items())
        ),
    )


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bot_response(
    value: Mapping[str, object],
    expected_ticket_id: str,
    config: FreshdeskAgentConfig,
) -> CSATResponse:
    source_id = value.get("id")
    ticket_id = value.get("ticket_id")
    survey_id = value.get("survey_id")
    created_at = value.get("created_at")
    ratings = value.get("ratings")
    if (
        not isinstance(source_id, int)
        or isinstance(source_id, bool)
        or not isinstance(ticket_id, int)
        or isinstance(ticket_id, bool)
        or str(ticket_id) != expected_ticket_id
        or not isinstance(survey_id, int)
        or isinstance(survey_id, bool)
        or not isinstance(created_at, str)
        or not isinstance(ratings, Mapping)
    ):
        raise FreshdeskCSATError("Freshdesk bot rating is invalid")
    rating_raw = ratings.get("default_question")
    if not isinstance(rating_raw, int) or isinstance(rating_raw, bool):
        raise FreshdeskCSATError("Freshdesk bot rating is invalid")
    responded_at = _utc_iso(created_at)
    comment_redacted = redact_survey_comment(value.get("feedback"))
    return CSATResponse(
        response_key=_source_id_hash(source_id),
        ticket_id=expected_ticket_id,
        survey_id=survey_id,
        responded_at=responded_at,
        rating_raw=rating_raw,
        satisfaction_bucket=config.bucket_for(survey_id, rating_raw),
        comment_present=comment_redacted is not None,
        comment_redacted=comment_redacted,
    )


def _source_id_hash(source_id: int) -> str:
    canonical = json.dumps(source_id, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _utc_iso(value: str) -> str:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise FreshdeskCSATError("Freshdesk response timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FreshdeskCSATError("Freshdesk response timestamp is invalid")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _retry_after(value: str | None) -> float:
    try:
        seconds = float(value) if value is not None else 60.0
    except ValueError:
        seconds = 60.0
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER_SECONDS)


def _check_fetch_deadline(should_stop: Callable[[], bool] | None) -> None:
    if should_stop is not None and should_stop():
        raise FreshdeskFetchDeadline("Freshdesk fetch duration limit reached")


@dataclass(frozen=True)
class FreshdeskAgentConfig:
    bot_agent_ids: frozenset[int]
    survey_scales: Mapping[str, Mapping[str, tuple[int, ...]]]

    def bucket_for(self, survey_id: int, rating_raw: int) -> str:
        scale = self.survey_scales.get(str(survey_id))
        if scale is None:
            raise FreshdeskCSATError("Freshdesk survey is not approved")
        matches = tuple(
            bucket for bucket in _BUCKETS if rating_raw in scale[bucket]
        )
        if len(matches) != 1:
            raise FreshdeskCSATError("Freshdesk rating token is not approved")
        return matches[0]


def resolve_exact_agent_id(
    ticket_fields: object,
    exact_display_name: str,
) -> int:
    """Resolve one exact choice from Freshdesk's default-agent field."""
    if not isinstance(ticket_fields, list) or not exact_display_name:
        raise FreshdeskCSATError("Freshdesk agent name did not resolve uniquely")
    matches: list[int] = []
    for field in ticket_fields:
        if not isinstance(field, Mapping):
            continue
        if field.get("type") != "default_agent" or field.get("name") != "agent":
            continue
        choices = field.get("choices")
        if not isinstance(choices, Mapping):
            continue
        identifier = choices.get(exact_display_name)
        if isinstance(identifier, int) and not isinstance(identifier, bool):
            matches.append(identifier)
    if len(matches) != 1:
        raise FreshdeskCSATError("Freshdesk agent name did not resolve uniquely")
    return matches[0]


def load_agent_config(path: Path) -> FreshdeskAgentConfig:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise FreshdeskCSATError("Freshdesk agent config is invalid") from None
    if not isinstance(value, Mapping) or set(value) != _CONFIG_KEYS:
        raise FreshdeskCSATError("Freshdesk agent config is invalid")
    if (
        value["schema_version"] != 1
        or value["approved_by"] != "PO"
        or not isinstance(value["approved_at"], str)
        or not isinstance(value["notes"], str)
    ):
        raise FreshdeskCSATError("Freshdesk agent config is invalid")
    try:
        date.fromisoformat(value["approved_at"])
    except ValueError:
        raise FreshdeskCSATError("Freshdesk agent config is invalid") from None
    raw_ids = value["bot_agent_ids"]
    if (
        not isinstance(raw_ids, list)
        or len(raw_ids) != 1
        or any(
            not isinstance(item, int) or isinstance(item, bool) or item <= 0
            for item in raw_ids
        )
    ):
        raise FreshdeskCSATError("Freshdesk agent config is invalid")
    scales = _parse_survey_scales(value["survey_scales"])
    return FreshdeskAgentConfig(
        bot_agent_ids=frozenset(raw_ids),
        survey_scales=scales,
    )


def write_approved_agent_config(
    path: Path,
    *,
    bot_agent_id: int,
    approved_at: date,
    survey_scales: Mapping[str, Mapping[str, Sequence[int]]],
) -> None:
    if (
        not isinstance(bot_agent_id, int)
        or isinstance(bot_agent_id, bool)
        or bot_agent_id <= 0
    ):
        raise FreshdeskCSATError("Freshdesk agent ID is invalid")
    normalized_scales = _parse_survey_scales(survey_scales)
    payload = {
        "schema_version": 1,
        "approved_by": "PO",
        "approved_at": approved_at.isoformat(),
        "bot_agent_ids": [bot_agent_id],
        "survey_scales": {
            survey_id: {
                bucket: list(scale[bucket]) for bucket in _BUCKETS
            }
            for survey_id, scale in normalized_scales.items()
        },
        "notes": (
            "Chi tinh response gan truc tiep cho Admin CS ZaloPay; "
            "ID/survey moi phai discovery va duyet lai"
        ),
    }
    _atomic_private_json(Path(path), payload)


def _parse_survey_scales(
    value: object,
) -> dict[str, dict[str, tuple[int, ...]]]:
    if not isinstance(value, Mapping) or not value:
        raise FreshdeskCSATError("Freshdesk survey scales are invalid")
    parsed: dict[str, dict[str, tuple[int, ...]]] = {}
    for survey_id, raw_scale in value.items():
        if (
            not isinstance(survey_id, str)
            or not survey_id.isdigit()
            or not isinstance(raw_scale, Mapping)
            or set(raw_scale) != set(_BUCKETS)
        ):
            raise FreshdeskCSATError("Freshdesk survey scales are invalid")
        scale: dict[str, tuple[int, ...]] = {}
        seen: set[int] = set()
        for bucket in _BUCKETS:
            tokens = raw_scale[bucket]
            if not isinstance(tokens, (list, tuple)):
                raise FreshdeskCSATError("Freshdesk survey scales are invalid")
            normalized = tuple(tokens)
            if any(
                not isinstance(token, int) or isinstance(token, bool)
                for token in normalized
            ) or seen.intersection(normalized):
                raise FreshdeskCSATError("Freshdesk survey scales are invalid")
            seen.update(normalized)
            scale[bucket] = normalized
        if not seen:
            raise FreshdeskCSATError("Freshdesk survey scales are invalid")
        parsed[survey_id] = scale
    return parsed


def _atomic_private_json(path: Path, payload: object) -> None:
    parent = path.parent
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        if not parent.is_dir():
            raise FreshdeskCSATError(
                "Freshdesk private file could not be written"
            ) from None
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=parent,
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
        raise FreshdeskCSATError("Freshdesk private file could not be written") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
