from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"
README = PROJECT_ROOT / "README.md"
GITIGNORE = PROJECT_ROOT / ".gitignore"
PACKAGE_JSON = PROJECT_ROOT / "package.json"
PLAYWRIGHT_CONFIG = PROJECT_ROOT / "playwright.config.ts"
E2E_SERVER = PROJECT_ROOT / "scripts" / "e2e_server.py"
E2E_SPEC = PROJECT_ROOT / "frontend" / "e2e" / "dashboard.spec.ts"
REPORTING_PACKAGE = PROJECT_ROOT / "src" / "weekly_cs_report"
REFRESH_DASHBOARD_DATA = PROJECT_ROOT / "scripts" / "refresh_dashboard_data.sh"


def _required_text(path: Path) -> str:
    assert path.is_file(), f"{path.name} must exist"
    return path.read_text(encoding="utf-8")


def _pyproject() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.9/3.10
        import tomli as tomllib

    return tomllib.loads(_required_text(PROJECT_ROOT / "pyproject.toml"))


def _docker_instruction(text: str, name: str) -> str:
    matches = [
        line.strip()
        for line in text.splitlines()
        if line.strip().upper().startswith(f"{name} ")
    ]
    assert len(matches) == 1, f"expected exactly one {name} instruction"
    return matches[0][len(name) :].strip()


def test_dockerignore_excludes_secrets_runtime_outputs_and_vcs_metadata():
    """Dropping an exclusion can send a secret or protected local output to Docker."""
    patterns_in_order = [
        line.strip()
        for line in _required_text(DOCKERIGNORE).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    patterns = set(patterns_in_order)

    assert {
        ".env",
        ".env.*",
        ".venv/",
        "artifacts/",
        "runtime/",
        ".superpowers/",
        ".pytest_cache/",
        "frontend/coverage/",
        "**/__pycache__/",
        "build/",
        "dist/",
        "*.egg-info/",
        ".git/",
        "assets/brand/fonts/source/",
        "config/freshdesk_reconciliation_agents.v1.json",
    } <= patterns
    assert patterns_in_order.index("!assets/**") < patterns_in_order.index(
        "assets/brand/fonts/source/"
    )


def test_gitignore_excludes_protected_runtime_snapshot():
    """A missing ignore rule can commit the ticket-level last-good snapshot."""
    patterns = {
        line.strip()
        for line in _required_text(GITIGNORE).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "runtime/" in patterns
    assert "config/freshdesk_reconciliation_agents.v1.json" in patterns


def test_reporting_package_keeps_freshdesk_credentials_inside_csat_cli_only():
    retired = (
        "dimension_backfill",
        "freshdesk_tpe_",
        "tpe_applicable_entry_points",
        "applicable_entry_points",
    )
    offenders = {
        path.relative_to(PROJECT_ROOT).as_posix(): [
            token for token in retired if token in path.read_text(encoding="utf-8")
        ]
        for path in REPORTING_PACKAGE.glob("*.py")
        if any(
            token in path.name or token in path.read_text(encoding="utf-8")
            for token in retired
        )
    }

    assert offenders == {}
    credential_tokens = ("FRESHDESK_BASE_URL", "FRESHDESK_API_KEY")
    credential_readers = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in REPORTING_PACKAGE.glob("*.py")
        if any(
            token in path.read_text(encoding="utf-8")
            for token in credential_tokens
        )
    }
    assert credential_readers == {"src/weekly_cs_report/cli.py"}

    serving_and_reporting = (
        "web.py",
        "report.py",
        "pipeline.py",
        "dimension_verifier.py",
        "dashboard_cache.py",
        "dashboard_schema.py",
    )
    for name in serving_and_reporting:
        text = _required_text(REPORTING_PACKAGE / name)
        if name == "web.py":
            # spec 2026-08-12-freshdesk-cookie-crawl-design.md SS6.3 carves out
            # one narrow exception: the serving process may perform exactly
            # one live cookie-verify call and persist the cookie file. It
            # must never import anything that fetches ticket or rating data,
            # and must never touch REST credentials.
            forbidden_freshdesk_names = (
                "FreshdeskClient",
                "FreshdeskSettings",
                "fetch_csat_population",
                "collect_ticket_ratings",
                "load_agent_config",
                "list_ticket_metadata",
                "get_satisfaction_ratings",
                "get_conversation_metadata",
            )
            assert not any(token in text for token in forbidden_freshdesk_names)
            assert "FRESHDESK_BASE_URL" not in text
            assert "FRESHDESK_API_KEY" not in text
        else:
            assert "freshdesk_csat" not in text
        assert all(token not in text for token in credential_tokens)


def test_freshdesk_refresh_orchestrator_keeps_network_reads_outside_web_process():
    text = _required_text(REFRESH_DASHBOARD_DATA)

    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    entry = text.index("weekly-cs-report fetch-freshdesk-entry-coverage")
    fetch = text.index("weekly-cs-report fetch-csat")
    reconcile = text.index("weekly-cs-report reconcile-freshdesk-outcomes")
    refresh = text.index("/api/refresh")
    assert entry < fetch < reconcile < refresh
    assert "http://127.0.0.1:" in text
    assert "X-Dashboard-Action: refresh" in text
    assert "FRESHDESK_API_KEY" not in text
    assert "FRESHDESK_BASE_URL" not in text
    assert "cat .env" not in text
    assert REFRESH_DASHBOARD_DATA.stat().st_mode & 0o111


def test_freshdesk_refresh_orchestrator_stops_before_publish_when_a_cache_job_is_partial(
    tmp_path: Path,
):
    """A duration-limited cache must never be published as today's complete data."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "calls.log"

    (fake_bin / "curl").write_text(
        "#!/usr/bin/env bash\n"
        "printf 'curl %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "printf '%s\\n' '{\"snapshot\":{\"generated_at\":\"before\"}}'\n",
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text(
        "#!/usr/bin/env bash\n"
        "printf 'uv %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "case \"$*\" in\n"
        "  *fetch-freshdesk-entry-coverage*) status=\"$ENTRY_STATUS\" ;;\n"
        "  *fetch-csat*) status=\"$FETCH_STATUS\" ;;\n"
        "  *) status=\"$RECONCILE_STATUS\" ;;\n"
        "esac\n"
        "printf '{\"status\":\"%s\"}\\n' \"$status\"\n",
        encoding="utf-8",
    )
    (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for executable in fake_bin.iterdir():
        executable.chmod(0o700)

    base_env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CALL_LOG": str(call_log),
    }
    cases = (
        (
            "duration_limit_reached",
            "complete",
            "complete",
            "Freshdesk entry coverage refresh did not complete",
            "fetch-csat",
        ),
        (
            "complete",
            "duration_limit_reached",
            "complete",
            "Freshdesk CSAT refresh did not complete",
            "reconcile-freshdesk-outcomes",
        ),
        (
            "complete",
            "complete",
            "duration_limit_reached",
            "Freshdesk outcome reconciliation did not complete",
            None,
        ),
    )

    for entry_status, fetch_status, reconcile_status, expected_error, forbidden_call in cases:
        call_log.write_text("", encoding="utf-8")
        result = subprocess.run(
            [str(REFRESH_DASHBOARD_DATA)],
            cwd=PROJECT_ROOT,
            env={
                **base_env,
                "ENTRY_STATUS": entry_status,
                "FETCH_STATUS": fetch_status,
                "RECONCILE_STATUS": reconcile_status,
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        calls = call_log.read_text(encoding="utf-8")
        assert result.returncode == 1
        assert expected_error in result.stderr
        assert "-X POST" not in calls
        if forbidden_call is not None:
            assert forbidden_call not in calls


def test_freshdesk_refresh_orchestrator_uses_one_worker_and_publishes_after_both_jobs(
    tmp_path: Path,
):
    """Serial Freshdesk reads avoid exhausting the observed per-ticket quota."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "calls.log"
    refreshed = tmp_path / "refreshed"

    (fake_bin / "curl").write_text(
        "#!/usr/bin/env bash\n"
        "printf 'curl %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "if [[ \"$*\" == *'-X POST'* ]]; then\n"
        "  : > \"$REFRESHED\"\n"
        "  printf '%s\\n' '{}'\n"
        "elif [[ -f \"$REFRESHED\" ]]; then\n"
        "  printf '%s\\n' '{\"snapshot\":{\"generated_at\":\"after\"}}'\n"
        "else\n"
        "  printf '%s\\n' '{\"snapshot\":{\"generated_at\":\"before\"}}'\n"
        "fi\n",
        encoding="utf-8",
    )
    (fake_bin / "uv").write_text(
        "#!/usr/bin/env bash\n"
        "printf 'uv %s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "printf '%s\\n' '{\"status\":\"complete\"}'\n",
        encoding="utf-8",
    )
    (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for executable in fake_bin.iterdir():
        executable.chmod(0o700)

    result = subprocess.run(
        [str(REFRESH_DASHBOARD_DATA)],
        cwd=PROJECT_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CALL_LOG": str(call_log),
            "REFRESHED": str(refreshed),
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    calls = call_log.read_text(encoding="utf-8").splitlines()
    uv_calls = [line for line in calls if line.startswith("uv ")]
    assert result.returncode == 0
    assert len(uv_calls) == 3
    assert all("--max-workers 1" in line for line in uv_calls)
    assert any("-X POST" in line for line in calls)


def test_dockerfile_has_an_explicit_secret_free_build_context():
    """A broad COPY or credential ENV can bake workspace secrets into the image."""
    text = _required_text(DOCKERFILE)
    copy_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("COPY ")
    ]

    assert copy_lines == [
        "COPY package.json package-lock.json ./",
        "COPY tsconfig.json tsconfig.app.json vite.config.ts playwright.config.ts ./",
        "COPY frontend/ ./frontend/",
        "COPY assets/ ./assets/",
        "COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:"
        "df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c"
        " /uv /bin/uv",
        "COPY pyproject.toml uv.lock README.md ./",
        "COPY src/ ./src/",
        "COPY --from=frontend /build/src/weekly_cs_report/static/spa/"
        " ./src/weekly_cs_report/static/spa/",
        "COPY --from=python-deps /opt/venv/ /opt/venv/",
        "COPY --from=python-deps /app/src/ ./src/",
        "COPY config/ ./config/",
        "COPY skills-snapshot/ ./skills-snapshot/",
        "COPY entrypoint.sh /app/entrypoint.sh",
    ]
    assert "LANGFUSE_" not in text
    assert not re.search(r"(?im)^ENV\s+DASHBOARD_AUTH_MODE\b", text)
    assert not re.search(r"(?im)^COPY\s+(?:--\\S+\s+)*[.*](?:\\s|$)", text)
    for forbidden in (".env", "artifacts", "runtime/"):
        assert all(forbidden not in line for line in copy_lines)


def test_dockerfile_uses_locked_dependencies_and_preserves_project_root_taxonomy():
    """The locked editable install must still resolve taxonomy from /app/config."""
    text = _required_text(DOCKERFILE)

    stages = [
        line.strip()
        for line in text.splitlines()
        if line.strip().upper().startswith("FROM ")
    ]
    assert stages == [
        "FROM node:24.18.0-bookworm-slim@sha256:"
        "6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d"
        " AS frontend",
        "FROM python:3.11.15-slim-bookworm@sha256:"
        "b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba"
        " AS python-deps",
        "FROM python:3.11.15-slim-bookworm@sha256:"
        "b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba"
        " AS runtime",
    ]
    assert "WORKDIR /app" in text
    assert (
        "UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --locked --no-dev "
        "--compile-bytecode"
        in text
    )
    assert "--no-editable" not in text
    assert "uv pip check --python /opt/venv/bin/python" in text
    assert "python -m pip install" not in text
    assert "COPY --from=python-deps /app/src/ ./src/" in text
    assert re.search(
        r"install -d -o dashboard -g dashboard -m 700 /app/runtime", text
    )
    assert "DASHBOARD_RUNTIME_DIR=/app/runtime" in text


def test_runtime_stage_ships_no_node_toolchain_or_source_map():
    """Shipping Node or a source map hands an attacker tooling and readable source."""
    text = _required_text(DOCKERFILE)
    runtime_stage = text.split(" AS runtime", 1)[1]

    for forbidden in ("node:", "npm ", "node_modules", "npx ", "/bin/uv"):
        assert forbidden not in runtime_stage
    assert "sourcemap" not in text.lower()
    # The build stage removes any map the bundler might emit.
    assert "-name '*.map' -delete" in text
    assert "DASHBOARD_FRONTEND_MODE=spa" in runtime_stage


def test_frontend_is_verified_before_it_can_be_copied_into_the_image():
    """A build that skips typecheck or tests can ship a broken bundle."""
    text = _required_text(DOCKERFILE)
    build_stage = text.split(" AS python-deps", 1)[0]

    assert "npm ci" in build_stage
    for step in ("npm run typecheck", "npm run test:unit", "npm run build"):
        assert step in build_stage


def test_e2e_script_rebuilds_the_bundle_before_playwright_starts():
    """A stale checked-in SPA can otherwise make a green browser run meaningless."""
    package = json.loads(_required_text(PACKAGE_JSON))

    assert package["scripts"]["test:e2e"] == "npm run build && playwright test"


def test_e2e_server_cannot_reuse_or_occupy_the_local_dashboard_port():
    """Browser tests must never replace or silently test the real service on 8765."""
    config = _required_text(PLAYWRIGHT_CONFIG)
    server = _required_text(E2E_SERVER)
    spec = _required_text(E2E_SPEC)

    assert "http://127.0.0.1:18765" in config
    assert 'const ORIGIN = "http://127.0.0.1:18765"' in spec
    assert "reuseExistingServer: false" in config
    assert 'os.environ.get("E2E_PORT", "18765")' in server
    assert "http://127.0.0.1:8765" not in config
    assert "http://127.0.0.1:8765" not in spec


def test_package_data_patterns_cover_every_nested_static_asset():
    """A flat pattern ships the SPA shell without its script, style or fonts."""
    package = PROJECT_ROOT / "src" / "weekly_cs_report"
    config = _pyproject()
    patterns = config["tool"]["setuptools"]["package-data"]["weekly_cs_report"]

    covered = {
        match.resolve()
        for pattern in patterns
        for match in package.glob(pattern)
        if match.is_file()
    }
    present = {
        path.resolve()
        for path in (package / "static").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }

    assert present, "the static directory must not be empty"
    assert present <= covered, sorted(
        str(path.relative_to(package)) for path in present - covered
    )


def test_container_runs_as_one_unprivileged_proxy_authenticated_service():
    """Root, local auth bypass, or multiple workers violate the deployment boundary."""
    text = _required_text(DOCKERFILE)
    cmd = json.loads(_docker_instruction(text, "CMD"))

    assert re.search(r"\bgroupadd\b[^\n]*--gid 10001\b[^\n]*\bdashboard\b", text)
    assert re.search(r"\buseradd\b[^\n]*--uid 10001\b[^\n]*\bdashboard\b", text)
    assert "USER 10001:10001" in text
    assert "EXPOSE 8080" in text
    assert cmd == [
        "weekly-cs-dashboard",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
    ]
    assert "--local" not in cmd
    assert "--workers" not in cmd


def test_readme_documents_exact_local_and_production_environment_contract():
    """Missing startup or variable names makes the service unsafe to operate."""
    text = _required_text(README)

    assert ".venv/bin/weekly-cs-dashboard --local --port 8765" in text
    for name in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "DASHBOARD_AUTH_MODE=proxy",
        "DASHBOARD_IDENTITY_HEADER",
        "DASHBOARD_RUNTIME_DIR",
    ):
        assert name in text
    assert "one worker" in text.lower()
    assert "5 phút" in text
    assert "last-good" in text
    assert "mode `700`" in text
    assert "mode `600`" in text


def test_readme_defines_identity_trust_boundary_and_devops_inputs():
    """An ambiguous proxy contract permits spoofed identity or an undeployable handoff."""
    text = _required_text(README)
    lower = text.lower()

    assert "terminate tls/sso" in lower
    assert "client-supplied identity header" in lower
    assert "strip" in lower
    assert "trusted identity header" in lower
    for term in (
        "internal registry",
        "runtime",
        "domain",
        "access policy",
        "egress",
        "https://langfuse.zalopay.vn",
        "approved secret storage",
    ):
        assert term in lower


def test_readme_states_browser_privacy_and_local_sharing_limits():
    """Omitting the allowlist boundary invites PII exposure or a false deployment claim."""
    text = _required_text(README)
    lower = text.lower()

    assert "ticket id" in lower
    for forbidden_browser_field in (
        "user id",
        "trans id",
        "phone",
        "names/emails",
        "conversation text",
        "prompts/responses",
        "raw payloads",
        "langfuse internal ids",
    ):
        assert forbidden_browser_field in lower
    assert "not browser fields" in lower
    assert "not a coworker-shareable deployment" in lower
    assert "container build was verified" not in lower


def test_readme_defines_single_replica_network_volume_and_probe_contracts():
    """An underspecified rollout can create duplicate refreshes or expose the service."""
    text = _required_text(README)
    lower = text.lower()

    for term in (
        "exactly one active replica",
        "recreate",
        "no surge",
        "networkpolicy",
        "ingress only from the authenticated reverse proxy",
        "runasuser: 10001",
        "runasgroup: 10001",
        "dedicated persistent-volume subdirectory",
        "chown 10001:10001",
        "chmod 0700",
        "chmod 0600",
        "/healthz",
        "liveness",
        "/readyz",
        "readiness",
        "503",
    ):
        assert term in lower


def test_readme_does_not_overstate_effective_data_freshness():
    """Calling the cache TTL a freshness SLA hides query time and stale-error periods."""
    lower = _required_text(README).lower()

    for term in (
        "successful cache commit",
        "refresh start",
        "refresh duration",
        "not a source-data freshness sla",
    ):
        assert term in lower
