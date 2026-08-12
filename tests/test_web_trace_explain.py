from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from weekly_cs_report.dashboard_cache import ProtectedSnapshotStore, SnapshotManager
from weekly_cs_report.langfuse_client import LangfuseClient
from weekly_cs_report.web import (
    WebSettings,
    _TRACE_EXPLAIN_CACHE_MISS,
    _TraceExplainCache,
    create_app,
)


def _unused_loader():
    raise AssertionError("snapshot loader must not run in trace-explain tests")


def _manager(tmp_path: Path) -> SnapshotManager:
    store = ProtectedSnapshotStore(tmp_path / "runtime")
    return SnapshotManager(_unused_loader, store)


def _langfuse_client(
    traces_by_session: dict[str, list[dict]],
    observations_by_trace: dict[str, list[dict]],
    *,
    on_request=None,
    max_attempts: int = 3,
) -> LangfuseClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        if request.url.path == "/api/public/traces":
            session_id = request.url.params["sessionId"]
            data = traces_by_session.get(session_id, [])
        else:
            trace_id = request.url.params["traceId"]
            data = observations_by_trace.get(trace_id, [])
        return httpx.Response(
            200,
            json={"data": data, "meta": {"page": 1, "limit": 100, "totalItems": len(data), "totalPages": 1}},
            request=request,
        )

    return LangfuseClient(
        "https://langfuse.example.test", "pk-test", "sk-test",
        transport=httpx.MockTransport(handler),
        max_attempts=max_attempts,
        sleep=lambda _seconds: None,
    )


def _app_with_client(tmp_path: Path, client: LangfuseClient):
    app = create_app(_manager(tmp_path), settings=WebSettings("off", "X-Forwarded-User"))
    app.state.langfuse_client = client
    return app


_NORMAL_TRACE = {
    "id": "trace-1",
    "sessionId": "7000001",
    "timestamp": "2026-08-01T02:00:00.000Z",
    "metadata": {"turn": 0},
    "input": {"user_input": "hoi ve giao dich", "source": "ticket", "other_info": {"freshdesk_id": "7000001"}},
    "output": {"response": "<p>da xu ly</p>", "agents_used": ["customer-service"], "elapsed_s": 5.0},
}
_NORMAL_OBSERVATIONS = [
    {"id": "o1", "traceId": "trace-1", "startTime": "2026-08-01T02:00:00.100Z", "name": "idempotency_guard", "input": {}, "output": {"blocked": False}},
    {"id": "o2", "traceId": "trace-1", "startTime": "2026-08-01T02:00:00.200Z", "name": "escalation_history_guard", "input": {}, "output": {"blocked": False}},
]


@pytest.mark.parametrize("ticket_id", ["abc", "12.3", "-5", "1" * 21, "1 2"])
def test_trace_explain_rejects_invalid_ticket_id(tmp_path, ticket_id):
    app = _app_with_client(tmp_path, _langfuse_client({}, {}))

    with TestClient(app) as client:
        response = client.get(f"/api/trace-explain/{ticket_id}")

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_ticket_id"}}


def test_trace_explain_returns_404_when_session_has_no_trace(tmp_path):
    app = _app_with_client(tmp_path, _langfuse_client({}, {}))

    with TestClient(app) as client:
        response = client.get("/api/trace-explain/7000099")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "trace_not_found"}}


def test_trace_explain_returns_503_when_langfuse_errors(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream down", request=_request)

    failing_client = LangfuseClient(
        "https://langfuse.example.test", "pk-test", "sk-test",
        transport=httpx.MockTransport(handler),
        max_attempts=1,
        sleep=lambda _seconds: None,
    )
    app = _app_with_client(tmp_path, failing_client)

    with TestClient(app) as client:
        response = client.get("/api/trace-explain/7000001")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "langfuse_unavailable"}}


def test_trace_explain_returns_503_when_no_langfuse_client_is_wired(tmp_path):
    app = create_app(_manager(tmp_path), settings=WebSettings("off", "X-Forwarded-User"))

    with TestClient(app) as client:
        response = client.get("/api/trace-explain/7000001")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "langfuse_unavailable"}}


def test_trace_explain_returns_200_with_serialized_explanation(tmp_path):
    client_stub = _langfuse_client(
        {"7000001": [_NORMAL_TRACE]}, {"trace-1": _NORMAL_OBSERVATIONS}
    )
    app = _app_with_client(tmp_path, client_stub)

    with TestClient(app) as client:
        response = client.get("/api/trace-explain/7000001")

    assert response.status_code == 200
    body = response.json()
    assert body["ticket_id"] == "7000001"
    assert len(body["turns"]) == 1
    turn = body["turns"][0]
    assert turn["verdict"] == "tra_loi"
    assert turn["verdict_reason"] == "Agent đã trả lời khách"
    assert [step["key"] for step in turn["steps"]] == [
        "idempotency_guard",
        "escalation_history_guard",
    ]
    assert body["langfuse_url"].startswith(
        "https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces?"
    )
    assert response.headers["cache-control"] == "no-store"


def test_trace_explain_second_request_is_served_from_cache(tmp_path):
    request_paths: list[str] = []
    client_stub = _langfuse_client(
        {"7000001": [_NORMAL_TRACE]},
        {"trace-1": _NORMAL_OBSERVATIONS},
        on_request=lambda request: request_paths.append(request.url.path),
    )
    app = _app_with_client(tmp_path, client_stub)

    with TestClient(app) as client:
        first = client.get("/api/trace-explain/7000001")
        second = client.get("/api/trace-explain/7000001")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    # One trace-list call + one observation-list call for trace-1; the
    # second HTTP request to our route must not repeat either of them.
    assert request_paths == ["/api/public/traces", "/api/public/observations"]


def test_trace_explain_cache_is_a_ttl_dict_distinguishing_miss_from_cached_none():
    ticks = iter([0.0, 100.0, 100.0, 10_000.0])
    cache = _TraceExplainCache(ttl_seconds=300.0, monotonic=lambda: next(ticks))

    assert cache.get("1") is _TRACE_EXPLAIN_CACHE_MISS
    cache.set("1", None)  # confirmed "no trace" is a real, cacheable outcome
    assert cache.get("1") is None
    assert cache.get("1") is None
    assert cache.get("1") is _TRACE_EXPLAIN_CACHE_MISS  # past the 300s TTL
