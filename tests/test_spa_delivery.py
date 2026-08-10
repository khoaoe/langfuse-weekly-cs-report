"""Delivery contract for the built React SPA.

The SPA is served by the same process, behind the same authentication, with a
strict policy that permits no inline or third-party code. These tests pin the
parts an operator cannot see by reading the page: caching, authentication on
static assets, traversal safety and the exact policy string.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from weekly_cs_report.web import (
    SPA_ASSET_CACHE_CONTROL,
    WebSettings,
    create_app,
    main,
    spa_index_path,
)

from tests.test_web import IDENTITY_HEADER, _snapshot, manager_factory  # noqa: F401


REQUIRED_SPA_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "script-src-attr 'none'",
    "style-src 'self'",
    "style-src-elem 'self'",
    "style-src-attr 'none'",
    "connect-src 'self'",
    "font-src 'self'",
    "img-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "worker-src 'none'",
)


@pytest.fixture()
def spa_client(manager_factory, tmp_path, monkeypatch):  # noqa: F811
    """A client whose SPA build lives in an isolated directory."""

    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text(
        '<!doctype html><html lang="vi"><head><title>Zalopay</title>'
        '<script type="module" src="/assets/index-abc123.js"></script>'
        '</head><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (spa / "assets" / "index-abc123.js").write_text("export {};\n", encoding="utf-8")
    (spa / "assets" / "index-abc123.css").write_text(":root{}\n", encoding="utf-8")
    monkeypatch.setattr("weekly_cs_report.web._SPA_ROOT", spa)

    generated_at = datetime(2026, 7, 29, 11, 27, tzinfo=timezone.utc)
    manager = manager_factory(initial=_snapshot(generated_at))
    return spa, manager


def _client(manager, *, mode: str = "spa", auth: str = "off") -> TestClient:
    return TestClient(
        create_app(manager, settings=WebSettings(auth, IDENTITY_HEADER, mode))
    )


def test_spa_document_is_never_cached_and_forbids_inline_code(spa_client):
    _spa, manager = spa_client
    with _client(manager) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    policy = response.headers["Content-Security-Policy"]
    for directive in REQUIRED_SPA_DIRECTIVES:
        assert directive in policy
    assert "unsafe-inline" not in policy
    assert "unsafe-eval" not in policy
    assert "sha256-" not in policy
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_hashed_assets_are_privately_cacheable_forever(spa_client):
    _spa, manager = spa_client
    with _client(manager) as client:
        response = client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == SPA_ASSET_CACHE_CONTROL
    assert SPA_ASSET_CACHE_CONTROL == "private, max-age=31536000, immutable"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_assets_require_the_same_proxy_identity_as_the_document(spa_client):
    _spa, manager = spa_client
    with _client(manager, auth="proxy") as client:
        anonymous = client.get("/assets/index-abc123.js")
        identified = client.get(
            "/assets/index-abc123.js", headers={IDENTITY_HEADER: "cs.lead"}
        )

    assert anonymous.status_code == 401
    assert identified.status_code == 200


def test_asset_auth_failures_and_missing_files_are_never_cached(spa_client):
    _spa, manager = spa_client
    with _client(manager, auth="proxy") as client:
        anonymous = client.get("/assets/index-abc123.js")
        missing = client.get(
            "/assets/missing.js", headers={IDENTITY_HEADER: "cs.lead"}
        )

    for response in (anonymous, missing):
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    "target",
    [
        "/assets/../index.html",
        "/assets/..%2f..%2fweb.py",
        "/assets/%2e%2e/%2e%2e/pyproject.toml",
        "/assets/nested/../../../../etc/passwd",
    ],
)
def test_asset_traversal_is_refused(spa_client, target):
    _spa, manager = spa_client
    with _client(manager) as client:
        response = client.get(target)

    assert response.status_code in {400, 404}
    assert "root" not in response.text


def test_assets_do_not_list_directories(spa_client):
    _spa, manager = spa_client
    with _client(manager) as client:
        assert client.get("/assets/").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404


def test_asset_symlinks_are_refused(spa_client, tmp_path):
    spa, manager = spa_client
    secret = tmp_path / "secret.txt"
    secret.write_text("credential", encoding="utf-8")
    (spa / "assets" / "leak.js").symlink_to(secret)

    with _client(manager) as client:
        response = client.get("/assets/leak.js")

    assert response.status_code == 404
    assert "credential" not in response.text


def test_legacy_mode_keeps_the_inline_page_and_its_hash_policy(spa_client):
    _spa, manager = spa_client
    with _client(manager, mode="legacy") as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    policy = response.headers["Content-Security-Policy"]
    assert "sha256-" in policy
    assert "unsafe-inline" not in policy


def test_spa_mode_falls_back_to_the_legacy_page_when_no_build_is_present(
    manager_factory, tmp_path, monkeypatch  # noqa: F811
):
    monkeypatch.setattr("weekly_cs_report.web._SPA_ROOT", tmp_path / "absent")
    generated_at = datetime(2026, 7, 29, 11, 27, tzinfo=timezone.utc)
    manager = manager_factory(initial=_snapshot(generated_at))

    with _client(manager) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "sha256-" in response.headers["Content-Security-Policy"]


def test_frontend_mode_must_be_a_known_value():
    with pytest.raises(ValueError):
        WebSettings("off", IDENTITY_HEADER, "experimental")


def test_spa_index_path_stays_inside_the_package():
    package_root = Path(__file__).resolve().parents[1] / "src" / "weekly_cs_report"
    assert package_root in spa_index_path().parents


def test_production_startup_refuses_a_missing_default_spa_build(
    monkeypatch, capsys
):
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "proxy")
    monkeypatch.delenv("DASHBOARD_FRONTEND_MODE", raising=False)
    monkeypatch.setattr("weekly_cs_report.web.spa_build_present", lambda: False)
    monkeypatch.setattr(
        "weekly_cs_report.web.load_environment",
        lambda: pytest.fail("startup must stop before reading credentials"),
    )

    assert main([]) == 2
    assert "SPA build is missing" in capsys.readouterr().err
