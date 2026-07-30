from __future__ import annotations

import json
import time
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx


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


class IngestionPartialFailure(LangfuseAPIError):
    def __init__(
        self,
        *,
        requested_ids: tuple[str, ...],
        success_ids: tuple[str, ...],
        error_ids: tuple[str, ...],
        status_code: int,
    ) -> None:
        self.requested_ids = requested_ids
        self.success_ids = success_ids
        self.error_ids = error_ids
        self.status_code = status_code
        RuntimeError.__init__(
            self,
            "status="
            f"{status_code} requested_ids={requested_ids!r} "
            f"success_ids={success_ids!r} error_ids={error_ids!r}",
        )


class ScoreReadbackTimeout(LangfuseAPIError):
    def __init__(self, score_id: str) -> None:
        self.score_id = score_id
        self.status_code = "timeout"
        RuntimeError.__init__(self, f"score_id={score_id} status=timeout")


class _DeadlineExceeded(RuntimeError):
    pass


class _RequestCancelled(RuntimeError):
    pass


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
    ) -> Iterator[dict]:
        from_utc = _serialize_utc(from_timestamp, "from_timestamp")
        to_utc = _serialize_utc(to_timestamp, "to_timestamp")
        page_number = 1

        while True:
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
            )
            data, total_pages = self._parse_page(
                response, "GET", "/api/public/traces"
            )
            yield from data
            if page_number >= total_pages:
                return
            page_number += 1

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
            _raise_if_cancelled(cancel_event)
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
            _raise_if_cancelled(cancel_event)
            if page_number >= total_pages:
                return
            page_number += 1

    def ingest_events(self, events: Sequence[dict]) -> IngestionReceipt:
        raise ReadOnlyOperationError

    def get_score(self, score_id: str) -> dict:
        raise ReadOnlyOperationError

    def _get_score(self, score_id: str, *, deadline: float | None = None) -> dict:
        path = f"/api/public/v2/scores/{_score_id_segment(score_id)}"
        response = self._request(
            "GET",
            path,
            expected_status=200,
            deadline=deadline,
        )
        payload = self._parse_object(response, "GET", path)
        if not isinstance(payload.get("id"), str) or not payload["id"]:
            raise LangfuseAPIError("GET", path, response.status_code)
        return payload

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
            _raise_if_cancelled(cancel_event)
            request_kwargs = dict(kwargs)
            if deadline is not None:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise _DeadlineExceeded
                request_kwargs["timeout"] = httpx.Timeout(min(30.0, remaining))
            try:
                response = self._client.request(method, path, **request_kwargs)
            except httpx.TransportError:
                _raise_if_cancelled(cancel_event)
                if deadline is not None and self._monotonic() >= deadline:
                    raise _DeadlineExceeded from None
                if attempt + 1 == self._max_attempts:
                    raise LangfuseAPIError(method, path, "transport_error") from None
                self._sleep_before_retry(attempt, deadline, cancel_event)
                continue

            if deadline is not None and self._monotonic() >= deadline:
                raise _DeadlineExceeded
            _raise_if_cancelled(cancel_event)
            if response.status_code == expected_status:
                return response
            if (
                response.status_code == 429
                or 500 <= response.status_code < 600
            ) and attempt + 1 < self._max_attempts:
                self._sleep_before_retry(attempt, deadline, cancel_event)
                continue
            raise LangfuseAPIError(method, path, response.status_code)

        raise AssertionError("unreachable")

    def _sleep_before_retry(
        self,
        attempt: int,
        deadline: float | None,
        cancel_event: threading.Event | None,
    ) -> None:
        _raise_if_cancelled(cancel_event)
        delay = self._backoff_base_s * (2**attempt)
        if deadline is not None:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise _DeadlineExceeded
            delay = min(delay, remaining)
        self._sleep(delay)
        _raise_if_cancelled(cancel_event)
        if deadline is not None and self._monotonic() >= deadline:
            raise _DeadlineExceeded

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


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _RequestCancelled


def _score_id_segment(score_id: str) -> str:
    if not isinstance(score_id, str) or not score_id:
        raise ValueError("score_id must be a non-empty string")
    return quote(score_id, safe="")


def _event_id(event: dict) -> str:
    if not isinstance(event, dict):
        raise ValueError("every event must be an object with a non-empty string id")
    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("every event must be an object with a non-empty string id")
    return event_id


def _result_ids(
    results: list[Any],
    method: str,
    path: str,
    status_code: int,
) -> tuple[str, ...]:
    ids: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            raise LangfuseAPIError(method, path, status_code)
        event_id = result.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise LangfuseAPIError(method, path, status_code)
        ids.append(event_id)
    return tuple(ids)
