from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest

from scripts.probe_freshdesk_csat_contract import (
    ContractProbeError,
    FreshdeskProbeSettings,
    load_probe_settings,
    run_contract_probe,
    summarize_shape,
    validate_contract_artifact,
)


def _rating(ticket_id: str, *, marker: str = "private-feedback") -> dict[str, object]:
    return {
        "id": int(ticket_id) + 900_000,
        "ticket_id": int(ticket_id),
        "survey_id": 42,
        "agent_id": 73_001,
        "created_at": "2026-07-21T00:00:00Z",
        "feedback": marker,
        "ratings": {"default_question": 103},
    }


def _safe_handler(marker: str, requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        ticket_id = request.url.path.split("/")[4]
        if request.url.path.endswith("/satisfaction_ratings"):
            return httpx.Response(200, json=[_rating(ticket_id, marker=marker)])
        if request.url.path.endswith("/conversations"):
            return httpx.Response(
                200,
                json=[
                    {
                        "user_id": 73_001,
                        "body_text": marker,
                        "from_email": f"{marker}@example.test",
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "id": int(ticket_id),
                "subject": marker,
                "description": marker,
                "responder_id": 73_001,
                "stats": {"agent_responded_at": None},
            },
        )

    return handler


def test_probe_persists_schema_not_values(tmp_path, capsys):
    marker = "PRIVATE-MARKER-0901234567"
    requests: list[httpx.Request] = []
    out = tmp_path / "private" / "contract.json"

    result = run_contract_probe(
        ticket_ids=("123",),
        settings=FreshdeskProbeSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="test-secret",
        ),
        transport=httpx.MockTransport(_safe_handler(marker, requests)),
        out=out,
    )

    captured = capsys.readouterr()
    serialized = json.dumps(result, ensure_ascii=False)
    written = out.read_text(encoding="utf-8")
    for sink in (captured.out, captured.err, serialized, written):
        assert marker not in sink
        assert "test-secret" not in sink
        assert "73001" not in sink
        assert "1020123" not in sink
    assert result["endpoints"]["satisfaction_ratings"]["shape"]["type"] == "list"
    assert result["identity_scan"] == {
        "weeks": 1,
        "completed": True,
        "ticket_count": 1,
        "checked_ticket_count": 1,
    }
    assert stat.S_IMODE(out.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert validate_contract_artifact(out) == result


def test_probe_uses_only_allowlisted_get_surfaces(tmp_path):
    requests: list[httpx.Request] = []
    run_contract_probe(
        ticket_ids=("123",),
        settings=FreshdeskProbeSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="secret",
        ),
        transport=httpx.MockTransport(_safe_handler("private", requests)),
        out=tmp_path / "contract.json",
    )

    assert requests
    assert {request.method for request in requests} == {"GET"}
    assert {request.url.host for request in requests} == {"vngzalopay.freshdesk.com"}
    assert {(request.url.path, request.url.query.decode()) for request in requests} == {
        ("/api/v2/tickets/123", ""),
        ("/api/v2/tickets/123", "include=stats"),
        ("/api/v2/tickets/123/conversations", "page=1&per_page=100"),
        ("/api/v2/tickets/123/satisfaction_ratings", ""),
    }


def test_probe_uses_rating_source_id_even_when_agent_attribution_is_null(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/satisfaction_ratings"):
            rating = _rating("123")
            rating["agent_id"] = None
            return httpx.Response(200, json=[rating])
        return _safe_handler("private", [])(request)

    result = run_contract_probe(
        ticket_ids=("123",),
        settings=FreshdeskProbeSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="secret",
        ),
        transport=httpx.MockTransport(handler),
        out=tmp_path / "contract.json",
    )

    assert result["identity_candidates"] == {
        "source_id_path": "satisfaction_ratings[].id",
        "missing_source_id_count": 0,
        "collision_count": 0,
    }


def test_probe_rejects_cross_origin_redirect_without_following_it(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "https://evil.example.test/stolen"},
        )

    with pytest.raises(ContractProbeError, match="redirect") as error:
        run_contract_probe(
            ticket_ids=("123",),
            settings=FreshdeskProbeSettings(
                base_url="https://vngzalopay.freshdesk.com",
                api_key="secret-marker",
            ),
            transport=httpx.MockTransport(handler),
            out=tmp_path / "contract.json",
        )

    assert len(requests) == 1
    assert requests[0].url.host == "vngzalopay.freshdesk.com"
    assert "secret-marker" not in str(error.value)


def test_probe_caps_retry_after_and_never_logs_response_body(tmp_path, capsys):
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "999"},
                text="PRIVATE-RATE-LIMIT-BODY",
            )
        return _safe_handler("private", [])(request)

    run_contract_probe(
        ticket_ids=("123",),
        settings=FreshdeskProbeSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="secret-marker",
        ),
        transport=httpx.MockTransport(handler),
        out=tmp_path / "contract.json",
        sleep=sleeps.append,
    )

    captured = capsys.readouterr()
    assert sleeps == [300.0]
    assert "PRIVATE-RATE-LIMIT-BODY" not in captured.out + captured.err


def test_probe_stops_streaming_at_the_response_byte_limit(tmp_path, capsys):
    tail_was_read = False

    class OversizedStream(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal tail_was_read
            yield b"x" * (5 * 1024 * 1024)
            yield b"y" * (5 * 1024 * 1024)
            yield b"z"
            tail_was_read = True
            yield b"PRIVATE-TAIL-MARKER"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=OversizedStream())

    with pytest.raises(ContractProbeError, match="byte limit"):
        run_contract_probe(
            ticket_ids=("123",),
            settings=FreshdeskProbeSettings(
                base_url="https://vngzalopay.freshdesk.com",
                api_key="secret",
            ),
            transport=httpx.MockTransport(handler),
            out=tmp_path / "contract.json",
        )

    captured = capsys.readouterr()
    assert tail_was_read is False
    assert "PRIVATE-TAIL-MARKER" not in captured.out + captured.err


def test_identity_checkpoint_resumes_without_refetching_completed_weeks(tmp_path):
    identity_requests: list[str] = []
    checkpoint = tmp_path / "private" / "identity_checkpoint.json"
    out = tmp_path / "private" / "contract.json"
    settings = FreshdeskProbeSettings(
        base_url="https://vngzalopay.freshdesk.com",
        api_key="secret",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        ticket_id = request.url.path.split("/")[4]
        if request.url.path.endswith("/satisfaction_ratings"):
            if ticket_id != "999":
                identity_requests.append(ticket_id)
            return httpx.Response(200, json=[_rating(ticket_id, marker="PRIVATE")])
        return _safe_handler("PRIVATE", [])(request)

    def first_run_clock() -> float:
        return 999.0 if len(identity_requests) >= 2 else 0.0

    first = run_contract_probe(
        ticket_ids=("999",),
        settings=settings,
        transport=httpx.MockTransport(handler),
        out=out,
        identity_ticket_ids_by_week={
            "2026-07-14": ("101", "102", "103"),
            "2026-07-21": ("104",),
        },
        identity_weeks=2,
        checkpoint=checkpoint,
        max_duration_seconds=10,
        monotonic=first_run_clock,
    )

    assert first["identity_scan"]["completed"] is False
    assert first["identity_scan"]["checked_ticket_count"] == 2
    assert identity_requests == ["101", "102"]
    assert stat.S_IMODE(checkpoint.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    checkpoint_text = checkpoint.read_text(encoding="utf-8")
    assert "PRIVATE" not in checkpoint_text
    assert "73001" not in checkpoint_text
    assert "900101" not in checkpoint_text

    identity_requests.clear()
    second = run_contract_probe(
        ticket_ids=("999",),
        settings=settings,
        transport=httpx.MockTransport(handler),
        out=out,
        identity_ticket_ids_by_week={
            "2026-07-14": ("101", "102", "103"),
            "2026-07-21": ("104",),
        },
        identity_weeks=2,
        checkpoint=checkpoint,
        max_duration_seconds=10,
        monotonic=lambda: 0.0,
    )

    assert second["identity_scan"]["completed"] is True
    assert second["identity_scan"]["checked_ticket_count"] == 4
    assert identity_requests == ["103", "104"]


def test_changed_identity_window_invalidates_checkpoint(tmp_path):
    checkpoint = tmp_path / "private" / "identity_checkpoint.json"
    out = tmp_path / "private" / "contract.json"
    requests: list[httpx.Request] = []
    first_settings = FreshdeskProbeSettings(
        base_url="https://vngzalopay.freshdesk.com",
        api_key="secret",
    )
    run_contract_probe(
        ticket_ids=("999",),
        settings=first_settings,
        transport=httpx.MockTransport(_safe_handler("private", requests)),
        out=out,
        identity_ticket_ids_by_week={"2026-07-14": ("101",)},
        checkpoint=checkpoint,
    )

    requests.clear()
    with pytest.raises(ContractProbeError, match="checkpoint"):
        run_contract_probe(
            ticket_ids=("999",),
            settings=first_settings,
            transport=httpx.MockTransport(_safe_handler("private", requests)),
            out=out,
            identity_ticket_ids_by_week={"2026-07-21": ("101",)},
            checkpoint=checkpoint,
        )
    assert requests == []


def test_load_settings_uses_exact_names_and_process_environment_wins(
    tmp_path, monkeypatch
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FRESHDESK_BASE_URL=https://vngzalopay.freshdesk.com\n"
        "FRESHDESK_API_KEY=file-secret\n"
        "UNRELATED_SECRET=ignore-me\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHDESK_BASE_URL", "https://vngzalopay.freshdesk.com")
    monkeypatch.setenv("FRESHDESK_API_KEY", "process-secret")

    settings = load_probe_settings(env_path)

    assert settings.base_url == "https://vngzalopay.freshdesk.com"
    assert settings.api_key == "process-secret"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://support.example.test",
        "https://user@support.example.test",
        "https://support.example.test/path",
        "https://support.example.test?query=1",
    ],
)
def test_settings_reject_non_origin_urls_without_exposing_secrets(
    tmp_path, monkeypatch, base_url
):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("FRESHDESK_BASE_URL", base_url)
    monkeypatch.setenv("FRESHDESK_API_KEY", "PRIVATE-API-KEY")

    with pytest.raises(ContractProbeError) as error:
        load_probe_settings(env_path)

    assert base_url not in str(error.value)
    assert "PRIVATE-API-KEY" not in str(error.value)


def test_settings_reject_other_https_tenant_before_any_request(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("FRESHDESK_BASE_URL", "https://other.example.test")
    monkeypatch.setenv("FRESHDESK_API_KEY", "PRIVATE-API-KEY")

    with pytest.raises(ContractProbeError):
        load_probe_settings(env_path)
    with pytest.raises(ContractProbeError):
        FreshdeskProbeSettings(
            base_url="https://other.example.test",
            api_key="PRIVATE-API-KEY",
        )


def test_schema_sample_size_is_bounded(tmp_path):
    settings = FreshdeskProbeSettings(
        base_url="https://vngzalopay.freshdesk.com",
        api_key="secret",
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    with pytest.raises(ContractProbeError, match="sample size"):
        run_contract_probe(
            ticket_ids=(),
            settings=settings,
            transport=transport,
            out=tmp_path / "contract.json",
        )
    with pytest.raises(ContractProbeError, match="sample size"):
        run_contract_probe(
            ticket_ids=tuple(str(value) for value in range(101)),
            settings=settings,
            transport=transport,
            out=tmp_path / "contract.json",
        )


def test_recursive_shape_summary_contains_types_not_values():
    marker = "PRIVATE-MARKER"
    result = summarize_shape(
        {"subject": marker, "stats": {"count": 3}, "items": [None, True]}
    )

    assert result == {
        "items": {"type": "list", "item_shapes": ["boolean", "null"]},
        "stats": {"count": "integer"},
        "subject": "string",
    }
    assert marker not in json.dumps(result)


def test_contract_validator_rejects_an_undocumented_raw_leaf(tmp_path):
    requests: list[httpx.Request] = []
    out = tmp_path / "contract.json"
    run_contract_probe(
        ticket_ids=("123",),
        settings=FreshdeskProbeSettings(
            base_url="https://vngzalopay.freshdesk.com",
            api_key="secret",
        ),
        transport=httpx.MockTransport(_safe_handler("private", requests)),
        out=out,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    payload["raw_response"] = "PRIVATE-MARKER"
    out.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractProbeError, match="artifact"):
        validate_contract_artifact(out)
