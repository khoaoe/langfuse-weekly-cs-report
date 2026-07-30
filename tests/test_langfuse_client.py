from __future__ import annotations

import base64
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from weekly_cs_report.langfuse_client import (
    LangfuseAPIError,
    LangfuseClient,
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

    with pytest.raises(RuntimeError):
        list(
            client.iter_observations_by_name(
                "route",
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
                deadline=10.0,
            )
        )

    assert transport.requests == []


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
