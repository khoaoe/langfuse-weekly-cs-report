from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from weekly_cs_report.dashboard_cache import ProtectedSnapshotStore, SnapshotManager
from weekly_cs_report.langfuse_client import LangfuseClient
from weekly_cs_report.web import WebSettings, create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "trace_explain"


def _unused_loader():
    raise AssertionError("snapshot loader must not run in why tests")


def _manager(tmp_path: Path) -> SnapshotManager:
    store = ProtectedSnapshotStore(tmp_path / "runtime")
    return SnapshotManager(_unused_loader, store)


def _page(data: list[dict]) -> dict:
    return {"data": data, "meta": {"page": 1, "limit": 100, "totalItems": len(data), "totalPages": 1}}


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _client_for_fixture(fixture: dict, *, on_request=None) -> LangfuseClient:
    traces_by_session: dict[str, list[dict]] = {}
    observations_by_trace: dict[str, list[dict]] = {}
    for entry in fixture.get("traces", []):
        trace = entry["trace"]
        traces_by_session.setdefault(trace["sessionId"], []).append(trace)
        observations_by_trace[trace["id"]] = entry["observations"]

    def handler(request: httpx.Request) -> httpx.Response:
        if on_request is not None:
            on_request(request)
        if request.url.path == "/api/public/traces":
            session_id = request.url.params["sessionId"]
            return httpx.Response(200, json=_page(traces_by_session.get(session_id, [])), request=request)
        trace_id = request.url.params["traceId"]
        return httpx.Response(200, json=_page(observations_by_trace.get(trace_id, [])), request=request)

    return LangfuseClient(
        "https://langfuse.example.test", "pk-test", "sk-test",
        transport=httpx.MockTransport(handler),
    )


def _app_with_client(tmp_path: Path, client: LangfuseClient):
    app = create_app(_manager(tmp_path), settings=WebSettings("off", "X-Forwarded-User"))
    app.state.langfuse_client = client
    return app


@pytest.mark.parametrize("ticket_id", ["abc", "12.3", "-5", "1" * 21, "1 2"])
def test_why_rejects_invalid_ticket_id(tmp_path, ticket_id):
    fixture = _load_fixture("escalation_e1_skill_guardrail_cs_escalation")
    app = _app_with_client(tmp_path, _client_for_fixture(fixture))

    with TestClient(app) as client:
        response = client.get(f"/api/trace-explain/{ticket_id}/why")

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_ticket_id"}}


def test_why_returns_404_when_session_has_no_trace(tmp_path):
    app = _app_with_client(tmp_path, _client_for_fixture({"traces": []}))

    with TestClient(app) as client:
        response = client.get("/api/trace-explain/7000099/why")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "trace_not_found"}}


def test_why_returns_503_when_no_langfuse_client_is_wired(tmp_path):
    app = create_app(_manager(tmp_path), settings=WebSettings("off", "X-Forwarded-User"))

    with TestClient(app) as client:
        response = client.get("/api/trace-explain/9001001/why")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "langfuse_unavailable"}}


def test_why_returns_dossier_disabled_llm_status(tmp_path):
    fixture = _load_fixture("escalation_e1_skill_guardrail_cs_escalation")
    app = _app_with_client(tmp_path, _client_for_fixture(fixture))

    with TestClient(app) as client:
        response = client.get(f"/api/trace-explain/{fixture['ticket_id']}/why")

    assert response.status_code == 200
    body = response.json()
    assert body["ticket_id"] == fixture["ticket_id"]
    assert body["escalation_class"] == "E1"
    assert body["narration"] is None
    assert body["llm_status"] == "disabled"
    # The fixture's synthetic load_skill_reference content is intentionally
    # shorter than the real skills-snapshot file, so drift is expected here.
    assert body["drift"] == {"changed": True}
    assert body["dossier"]["escalation_class"] == "E1"
    assert body["dossier"]["blocking_rule"] == "cs_escalation"
    # PII boundary: no internal Langfuse ids ever reach this payload.
    serialized = json.dumps(body, ensure_ascii=False)
    assert "traceId" not in serialized
    assert "sessionId" not in serialized
    assert response.headers["cache-control"] == "no-store"


def test_why_second_request_is_served_from_cache(tmp_path):
    fixture = _load_fixture("escalation_e1_skill_guardrail_cs_escalation")
    request_paths: list[str] = []
    app = _app_with_client(
        tmp_path,
        _client_for_fixture(fixture, on_request=lambda r: request_paths.append(r.url.path)),
    )

    with TestClient(app) as client:
        first = client.get(f"/api/trace-explain/{fixture['ticket_id']}/why")
        second = client.get(f"/api/trace-explain/{fixture['ticket_id']}/why")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    # The second HTTP request must not repeat any upstream Langfuse call.
    assert request_paths.count("/api/public/observations") == 1
