from __future__ import annotations

import json
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = PROJECT_ROOT / "Dockerfile"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"
README = PROJECT_ROOT / "README.md"
GITIGNORE = PROJECT_ROOT / ".gitignore"


def _required_text(path: Path) -> str:
    assert path.is_file(), f"{path.name} must exist"
    return path.read_text(encoding="utf-8")


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
    patterns = {
        line.strip()
        for line in _required_text(DOCKERIGNORE).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        ".env",
        ".env.*",
        ".venv/",
        "artifacts/",
        "runtime/",
        ".superpowers/",
        ".pytest_cache/",
        "**/__pycache__/",
        "build/",
        "dist/",
        "*.egg-info/",
        ".git/",
    } <= patterns


def test_gitignore_excludes_protected_runtime_snapshot():
    """A missing ignore rule can commit the ticket-level last-good snapshot."""
    patterns = {
        line.strip()
        for line in _required_text(GITIGNORE).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "runtime/" in patterns


def test_dockerfile_has_an_explicit_secret_free_build_context():
    """A broad COPY or credential ENV can bake workspace secrets into the image."""
    text = _required_text(DOCKERFILE)
    copy_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("COPY ")
    ]

    assert copy_lines == [
        "COPY pyproject.toml README.md ./",
        "COPY src/ ./src/",
        "COPY config/ ./config/",
    ]
    assert "LANGFUSE_" not in text
    assert not re.search(r"(?im)^ENV\s+DASHBOARD_AUTH_MODE\b", text)
    assert not re.search(r"(?im)^COPY\s+(?:--\\S+\s+)*[.*](?:\\s|$)", text)
    for forbidden in (".env", "artifacts", "runtime/"):
        assert all(forbidden not in line for line in copy_lines)


def test_dockerfile_preserves_project_root_taxonomy_and_protected_runtime():
    """A non-editable install or permissive runtime breaks taxonomy lookup or cache safety."""
    text = _required_text(DOCKERFILE)

    assert text.splitlines()[0] == "FROM python:3.11-slim"
    assert "WORKDIR /app" in text
    assert re.search(r"python -m pip install\b[^\n]*\s-e \.", text)
    assert re.search(
        r"install -d -o dashboard -g dashboard -m 700 /app/runtime", text
    )
    assert "DASHBOARD_RUNTIME_DIR=/app/runtime" in text


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
