from __future__ import annotations

import os
import re
import socket
import time
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Any

import httpx


_DNS_OVERRIDE_ENV = "LANGFUSE_DNS_OVERRIDE"
_SESSION_ID_PATTERN = re.compile(r"[0-9]+\Z")
_real_getaddrinfo = socket.getaddrinfo
_dns_override_applied: str | None = None


def _apply_dns_override() -> None:
    """Resolve one hostname to a fixed IP when the platform has no route to it.

    Some deploy platforms (e.g. a shared PaaS) reach the target host fine over
    TCP but have no DNS path to an internal-only name. This substitutes the
    DNS answer only, so TLS SNI/cert validation still runs against the real
    hostname. Real production leaves LANGFUSE_DNS_OVERRIDE unset.
    """
    global _dns_override_applied
    raw = os.environ.get(_DNS_OVERRIDE_ENV, "")
    if not raw or raw == _dns_override_applied:
        return
    host, sep, ip = raw.partition(":")
    if not sep or not host or not ip:
        raise ValueError(f"{_DNS_OVERRIDE_ENV} must be host:ip")

    def _patched(getaddr_host: str, *args: Any, **kwargs: Any) -> Any:
        return _real_getaddrinfo(
            ip if getaddr_host == host else getaddr_host, *args, **kwargs
        )

    socket.getaddrinfo = _patched
    _dns_override_applied = raw


@dataclass(frozen=True)
class IngestionReceipt:
    requested_ids: tuple[str, ...]
    success_ids: tuple[str, ...]


class LangfuseAPIError(RuntimeError):
    def __init__(
        self,
        method: str,
        path: str,
        status_code: int | str,
    ) -> None:
        self.method = method
        self.path = path
        self.status_code = status_code
        super().__init__(f"{method} {path} status={status_code}")


class ReadOnlyOperationError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Langfuse client permits read-only reporting")


class LangfuseTracePageLimitExceeded(LangfuseAPIError):
    def __init__(self) -> None:
        super().__init__(
            "GET",
            "/api/public/traces",
            "page_limit_exceeded",
        )


class LangfuseDeadlineExceeded(LangfuseAPIError):
    def __init__(self, method: str, path: str) -> None:
        super().__init__(method, path, "deadline_exceeded")


class LangfuseRequestCancelled(LangfuseAPIError):
    def __init__(self, method: str, path: str) -> None:
        super().__init__(method, path, "cancelled")


class LangfuseClient:
    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_attempts: int = 3,
        backoff_base_s: float = 0.5,
        poll_interval_s: float = 0.5,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if backoff_base_s < 0:
            raise ValueError("backoff_base_s must not be negative")
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be positive")

        _apply_dns_override()
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(public_key, secret_key),
            timeout=httpx.Timeout(30.0),
            verify=True,
            transport=transport,
        )
        self._sleep = sleep
        self._monotonic = monotonic
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._poll_interval_s = poll_interval_s

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LangfuseClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def iter_traces(
        self,
        from_timestamp: datetime,
        to_timestamp: datetime,
        *,
        deadline: float | None = None,
        cancel_event: threading.Event | None = None,
        max_pages: int = 500,
    ) -> Iterator[dict]:
        if (
            not isinstance(max_pages, int)
            or isinstance(max_pages, bool)
            or not 1 <= max_pages <= 500
        ):
            raise ValueError("max_pages must be an integer between 1 and 500")
        from_utc = _serialize_utc(from_timestamp, "from_timestamp")
        to_utc = _serialize_utc(to_timestamp, "to_timestamp")
        page_number = 1

        while True:
            _raise_if_cancelled(cancel_event, "GET", "/api/public/traces")
            params = {
                "page": page_number,
                "limit": 100,
                "fromTimestamp": from_utc,
                "toTimestamp": to_utc,
                "orderBy": "timestamp.asc",
                "fields": "core,io",
            }
            response = self._request(
                "GET",
                "/api/public/traces",
                params=params,
                expected_status=200,
                deadline=deadline,
                cancel_event=cancel_event,
            )
            data, total_pages = self._parse_page(
                response, "GET", "/api/public/traces"
            )
            if total_pages > max_pages:
                raise LangfuseTracePageLimitExceeded
            yield from data
            _raise_if_cancelled(cancel_event, "GET", "/api/public/traces")
            if page_number >= total_pages:
                return
            page_number += 1

    def list_traces_by_session(self, session_id: str) -> list[dict]:
        """Read every trace of one session, sorted by timestamp ascending."""
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("session_id must be a non-empty numeric string")

        traces: list[dict] = []
        page_number = 1
        while True:
            response = self._request(
                "GET",
                "/api/public/traces",
                params={
                    "sessionId": session_id,
                    "fields": "core,io",
                    "page": page_number,
                    "limit": 100,
                    "orderBy": "timestamp.asc",
                },
                expected_status=200,
            )
            data, total_pages = self._parse_page(
                response, "GET", "/api/public/traces"
            )
            traces.extend(data)
            if page_number >= total_pages:
                break
            page_number += 1
        traces.sort(key=lambda item: item.get("timestamp") or "")
        return traces

    def list_observations(self, trace_id: str) -> list[dict]:
        observations: list[dict] = []
        page_number = 1

        while True:
            response = self._request(
                "GET",
                "/api/public/observations",
                params={"traceId": trace_id, "page": page_number, "limit": 100},
                expected_status=200,
            )
            data, total_pages = self._parse_page(
                response, "GET", "/api/public/observations"
            )
            observations.extend(data)
            if page_number >= total_pages:
                return observations
            page_number += 1

    def iter_observations_by_name(
        self,
        name: str,
        from_start_time: datetime,
        to_start_time: datetime,
        *,
        deadline: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[dict]:
        """Read one observation name in bounded pages (the API caps at 100)."""
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        from_utc = _serialize_utc(from_start_time, "from_start_time")
        to_utc = _serialize_utc(to_start_time, "to_start_time")
        page_number = 1
        while True:
            _raise_if_cancelled(
                cancel_event,
                "GET",
                "/api/public/observations",
            )
            response = self._request(
                "GET",
                "/api/public/observations",
                params={
                    "name": name,
                    "fromStartTime": from_utc,
                    "toStartTime": to_utc,
                    "page": page_number,
                    "limit": 100,
                },
                expected_status=200,
                deadline=deadline,
                cancel_event=cancel_event,
            )
            data, total_pages = self._parse_page(
                response, "GET", "/api/public/observations"
            )
            yield from data
            _raise_if_cancelled(
                cancel_event,
                "GET",
                "/api/public/observations",
            )
            if page_number >= total_pages:
                return
            page_number += 1

    def ingest_events(self, events: Sequence[dict]) -> IngestionReceipt:
        raise ReadOnlyOperationError

    def get_score(self, score_id: str) -> dict:
        raise ReadOnlyOperationError

    def wait_for_score(
        self,
        score_id: str,
        predicate: Callable[[dict], bool],
        timeout_s: float,
    ) -> dict:
        raise ReadOnlyOperationError

    def delete_score(self, score_id: str) -> None:
        raise ReadOnlyOperationError

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        deadline: float | None = None,
        cancel_event: threading.Event | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        if (method, path) not in {
            ("GET", "/api/public/traces"),
            ("GET", "/api/public/observations"),
        }:
            raise ReadOnlyOperationError
        for attempt in range(self._max_attempts):
            _raise_if_cancelled(cancel_event, method, path)
            request_kwargs = dict(kwargs)
            if deadline is not None:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise LangfuseDeadlineExceeded(method, path)
                request_kwargs["timeout"] = httpx.Timeout(min(30.0, remaining))
            try:
                response = self._client.request(method, path, **request_kwargs)
            except httpx.TransportError:
                _raise_if_cancelled(cancel_event, method, path)
                if deadline is not None and self._monotonic() >= deadline:
                    raise LangfuseDeadlineExceeded(method, path) from None
                if attempt + 1 == self._max_attempts:
                    raise LangfuseAPIError(method, path, "transport_error") from None
                self._sleep_before_retry(
                    attempt,
                    deadline,
                    cancel_event,
                    method,
                    path,
                )
                continue

            if deadline is not None and self._monotonic() >= deadline:
                raise LangfuseDeadlineExceeded(method, path)
            _raise_if_cancelled(cancel_event, method, path)
            if response.status_code == expected_status:
                return response
            if (
                response.status_code == 429
                or 500 <= response.status_code < 600
            ) and attempt + 1 < self._max_attempts:
                self._sleep_before_retry(
                    attempt,
                    deadline,
                    cancel_event,
                    method,
                    path,
                )
                continue
            raise LangfuseAPIError(method, path, response.status_code)

        raise AssertionError("unreachable")

    def _sleep_before_retry(
        self,
        attempt: int,
        deadline: float | None,
        cancel_event: threading.Event | None,
        method: str,
        path: str,
    ) -> None:
        _raise_if_cancelled(cancel_event, method, path)
        delay = self._backoff_base_s * (2**attempt)
        if deadline is not None:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise LangfuseDeadlineExceeded(method, path)
            delay = min(delay, remaining)
        self._sleep(delay)
        _raise_if_cancelled(cancel_event, method, path)
        if deadline is not None and self._monotonic() >= deadline:
            raise LangfuseDeadlineExceeded(method, path)

    @staticmethod
    def _parse_object(
        response: httpx.Response,
        method: str,
        path: str,
    ) -> dict:
        try:
            payload = response.json()
        except ValueError:
            raise LangfuseAPIError(method, path, response.status_code) from None
        if not isinstance(payload, dict):
            raise LangfuseAPIError(method, path, response.status_code)
        return payload

    @classmethod
    def _parse_page(
        cls,
        response: httpx.Response,
        method: str,
        path: str,
    ) -> tuple[list[dict], int]:
        payload = cls._parse_object(response, method, path)
        data = payload.get("data")
        meta = payload.get("meta")
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise LangfuseAPIError(method, path, response.status_code)
        if not all(isinstance(item, dict) for item in data):
            raise LangfuseAPIError(method, path, response.status_code)
        total_pages = meta.get("totalPages")
        if (
            not isinstance(total_pages, int)
            or isinstance(total_pages, bool)
            or total_pages < 0
        ):
            raise LangfuseAPIError(method, path, response.status_code)
        return data, total_pages


def _serialize_utc(value: datetime, field_name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _raise_if_cancelled(
    cancel_event: threading.Event | None,
    method: str,
    path: str,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise LangfuseRequestCancelled(method, path)
