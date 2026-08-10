from __future__ import annotations

import base64
from datetime import datetime, timezone
import threading
from zoneinfo import ZoneInfo

import httpx
import pytest

from weekly_cs_report.langfuse_client import (
    LangfuseAPIError,
    LangfuseClient,
    LangfuseDeadlineExceeded,
    ReadOnlyOperationError,
)


BASE_URL = "https://langfuse.example.test"
PUBLIC_KEY = "pk-test-sensitive"
SECRET_KEY = "sk-test-sensitive"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def page(data: list[dict], total_pages: int = 1) -> dict:
    return {
        "data": data,
        "meta": {"page": 1, "limit": 100, "totalItems": len(data), "totalPages": total_pages},
    }


def client_for(handler) -> LangfuseClient:
    return LangfuseClient(
        BASE_URL,
        PUBLIC_KEY,
        SECRET_KEY,
        transport=httpx.MockTransport(handler),
    )


class TrackingTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.close_calls = 0
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=page([]), request=request)

    def close(self) -> None:
        self.close_calls += 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts must be between 1 and 3"),
        ({"max_attempts": 4}, "max_attempts must be between 1 and 3"),
        ({"backoff_base_s": -0.5}, "backoff_base_s must not be negative"),
        ({"poll_interval_s": 0}, "poll_interval_s must be positive"),
    ],
    ids=("attempts-too-low", "attempts-too-high", "negative-backoff", "zero-poll"),
)
def test_client_rejects_invalid_retry_configuration_before_http_client_creation(
    monkeypatch,
    kwargs: dict[str, float | int],
    message: str,
):
    client_creations = 0

    def fail_if_http_client_is_created(*_args, **_kwargs):
        nonlocal client_creations
        client_creations += 1
        raise AssertionError("invalid configuration must not create an HTTP client")

    monkeypatch.setattr(
        "weekly_cs_report.langfuse_client.httpx.Client",
        fail_if_http_client_is_created,
    )

    with pytest.raises(ValueError, match=message):
        LangfuseClient(BASE_URL, PUBLIC_KEY, SECRET_KEY, **kwargs)

    assert client_creations == 0


def test_client_context_manager_closes_owned_httpx_client():
    transport = TrackingTransport()
    client = LangfuseClient(
        BASE_URL,
        PUBLIC_KEY,
        SECRET_KEY,
        transport=transport,
    )

    with client as entered:
        assert entered is client
        assert list(
            entered.iter_traces(
                datetime(2026, 5, 4, tzinfo=timezone.utc),
                datetime(2026, 5, 5, tzinfo=timezone.utc),
            )
        ) == []

    assert transport.close_calls == 1
    with pytest.raises(RuntimeError, match="closed"):
        list(
            client.iter_traces(
                datetime(2026, 5, 4, tzinfo=timezone.utc),
                datetime(2026, 5, 5, tzinfo=timezone.utc),
            )
        )


def test_read_operations_use_only_approved_get_paths_and_keep_authentication():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=page([]), request=request)

    client = client_for(handler)

    assert list(
        client.iter_traces(
            datetime(2026, 5, 4, tzinfo=timezone.utc),
            datetime(2026, 7, 29, 12, tzinfo=TZ),
        )
    ) == []
    assert client.list_observations("trace/with space") == []

    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/public/traces"),
        ("GET", "/api/public/observations"),
    ]
    assert dict(requests[0].url.params) == {
        "page": "1",
        "limit": "100",
        "fromTimestamp": "2026-05-04T00:00:00Z",
        "toTimestamp": "2026-07-29T05:00:00Z",
        "orderBy": "timestamp.asc",
        "fields": "core,io",
    }
    expected_auth = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
    assert requests[0].headers["Authorization"] == f"Basic {expected_auth}"


def test_iter_observations_by_name_uses_get_name_time_bounds_and_hard_limit_100():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page_number = int(request.url.params["page"])
        return httpx.Response(
            200,
            json=page([{"traceId": f"trace-{page_number}"}] if page_number == 1 else [], 2),
            request=request,
        )

    client = client_for(handler)
    rows = list(
        client.iter_observations_by_name(
            "route",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
        )
    )

    assert rows == [{"traceId": "trace-1"}]
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/public/observations"),
        ("GET", "/api/public/observations"),
    ]
    assert dict(requests[0].url.params) == {
        "name": "route", "fromStartTime": "2026-07-01T00:00:00Z",
        "toStartTime": "2026-07-02T00:00:00Z", "page": "1", "limit": "100",
    }


def test_iter_observations_by_name_honors_shared_deadline_before_request():
    transport = TrackingTransport()
    client = LangfuseClient(
        BASE_URL,
        PUBLIC_KEY,
        SECRET_KEY,
        transport=transport,
        monotonic=lambda: 10.0,
    )

    with pytest.raises(LangfuseDeadlineExceeded) as captured:
        list(
            client.iter_observations_by_name(
                "route",
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
                deadline=10.0,
            )
        )

    assert captured.value.method == "GET"
    assert captured.value.path == "/api/public/observations"
    assert captured.value.status_code == "deadline_exceeded"
    assert transport.requests == []


def test_iter_traces_rejects_advertised_page_count_above_limit_before_yielding():
    """An unbounded upstream page count must not leak the first page into analysis."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=page([{"id": "trace-should-not-yield"}], total_pages=501),
            request=request,
        )

    with pytest.raises(LangfuseAPIError) as captured:
        list(
            client_for(handler).iter_traces(
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
                max_pages=500,
            )
        )

    assert type(captured.value).__name__ == "LangfuseTracePageLimitExceeded"
    assert captured.value.method == "GET"
    assert captured.value.path == "/api/public/traces"
    assert captured.value.status_code == "page_limit_exceeded"
    assert len(requests) == 1


def test_iter_traces_stops_for_cancellation_before_the_next_request():
    """Shutdown must stop pagination before it begins another HTTP request."""
    requests: list[httpx.Request] = []
    cancel_event = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        cancel_event.set()
        return httpx.Response(
            200,
            json=page([{"id": "first-page"}], total_pages=2),
            request=request,
        )

    with pytest.raises(LangfuseAPIError) as captured:
        list(
            client_for(handler).iter_traces(
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
                cancel_event=cancel_event,
            )
        )

    assert type(captured.value).__name__ == "LangfuseRequestCancelled"
    assert captured.value.method == "GET"
    assert captured.value.path == "/api/public/traces"
    assert captured.value.status_code == "cancelled"
    assert len(requests) == 1


def test_iter_traces_limits_http_timeout_to_remaining_refresh_budget():
    """A near deadline must shorten HTTPX's request timeout below its 30-second cap."""
    observed_timeouts: list[dict[str, float | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, json=page([]), request=request)

    client = LangfuseClient(
        BASE_URL,
        PUBLIC_KEY,
        SECRET_KEY,
        transport=httpx.MockTransport(handler),
        monotonic=lambda: 100.0,
    )

    assert list(
        client.iter_traces(
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            deadline=105.0,
        )
    ) == []
    assert observed_timeouts == [
        {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}
    ]


@pytest.mark.parametrize("field", ["from_timestamp", "to_timestamp"])
def test_iter_traces_rejects_naive_timestamp_before_request(field: str):
    requests: list[httpx.Request] = []
    client = client_for(lambda request: requests.append(request))
    values = {
        "from_timestamp": datetime(2026, 5, 4),
        "to_timestamp": datetime(2026, 7, 29, tzinfo=timezone.utc),
    }
    if field == "to_timestamp":
        values = {
            "from_timestamp": datetime(2026, 5, 4, tzinfo=timezone.utc),
            "to_timestamp": datetime(2026, 7, 29),
        }

    with pytest.raises(ValueError, match=f"{field} must be timezone-aware"):
        list(client.iter_traces(**values))

    assert requests == []


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.ingest_events(
            [{"id": "event-1", "body": {"raw": "sensitive-body"}}]
        ),
        lambda client: client.get_score("sensitive-score"),
        lambda client: client.wait_for_score(
            "sensitive-score", lambda _score: True, timeout_s=1
        ),
        lambda client: client.delete_score("sensitive-score"),
    ],
    ids=("ingestion", "score-get", "score-poll", "score-delete"),
)
def test_write_and_score_operations_fail_closed_before_transport(operation):
    transport = TrackingTransport()
    client = LangfuseClient(
        BASE_URL,
        PUBLIC_KEY,
        SECRET_KEY,
        transport=transport,
    )

    with pytest.raises(ReadOnlyOperationError) as captured:
        operation(client)

    assert str(captured.value) == "Langfuse client permits read-only reporting"
    assert PUBLIC_KEY not in str(captured.value)
    assert SECRET_KEY not in str(captured.value)
    assert "sensitive-body" not in str(captured.value)
    assert transport.requests == []


def test_client_exposes_no_private_score_readback_escape_hatch():
    """Read-only score guards must not be bypassable through a private method."""
    assert {
        name
        for name in LangfuseClient.__dict__
        if name.startswith("_") and not name.startswith("__") and "score" in name
    } == set()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/public/ingestion"),
        ("GET", "/api/public/v2/scores/score-1"),
        ("DELETE", "/api/public/scores/score-1"),
        ("GET", "/api/public/traces/score-1"),
        ("PATCH", "/api/public/observations"),
    ],
)
def test_transport_boundary_rejects_every_unapproved_method_or_path(method, path):
    transport = TrackingTransport()
    client = LangfuseClient(
        BASE_URL,
        PUBLIC_KEY,
        SECRET_KEY,
        transport=transport,
    )

    with pytest.raises(ReadOnlyOperationError, match="read-only reporting"):
        client._request(method, path, expected_status=200)

    assert transport.requests == []


def test_read_api_errors_remain_redacted():
    with pytest.raises(LangfuseAPIError) as captured:
        client_for(
            lambda request: httpx.Response(
                401,
                text=f"body contains {PUBLIC_KEY} {SECRET_KEY} and raw ticket",
                request=request,
            )
        ).list_observations("trace-1")

    assert str(captured.value) == "GET /api/public/observations status=401"
    assert PUBLIC_KEY not in str(captured.value)
    assert SECRET_KEY not in str(captured.value)
