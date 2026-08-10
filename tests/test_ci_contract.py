from __future__ import annotations

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
GITIGNORE = PROJECT_ROOT / ".gitignore"

PINNED_ACTIONS = {
    "actions/checkout": (
        "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "v7.0.1",
    ),
    "actions/setup-node": (
        "820762786026740c76f36085b0efc47a31fe5020",
        "v7.0.0",
    ),
    "actions/setup-python": (
        "5fda3b95a4ea91299a34e894583c3862153e4b97",
        "v7.0.0",
    ),
    "actions/upload-artifact": (
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "v7.0.1",
    ),
}


def _workflow() -> str:
    assert WORKFLOW.is_file(), "the production candidate needs a CI workflow"
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_has_least_privilege_cancellation_and_pinned_actions():
    text = _workflow()

    assert re.search(r"(?m)^permissions:\n  contents: read$", text)
    assert "group: ${{ github.workflow }}-${{ github.ref }}" in text
    assert "cancel-in-progress: true" in text

    action_uses = re.findall(r"uses:\s+([^@\s]+)@([0-9a-f]{40})", text)
    assert action_uses, "every action must be pinned to a full commit SHA"
    assert {name for name, _ in action_uses} == set(PINNED_ACTIONS)
    for name, (sha, version) in PINNED_ACTIONS.items():
        assert f"uses: {name}@{sha} # {version}" in text

    assert not re.search(r"uses:\s+\S+@v\d", text)


def test_ci_runs_the_frontend_python_browser_and_dependency_gates():
    text = _workflow()

    for required in (
        "runs-on: ubuntu-24.04",
        "node-version: 24.18.0",
        'test "$(npm --version)" = "11.16.0"',
        "npm ci",
        "npm audit --audit-level=high",
        "npm audit --audit-level=high --omit=dev",
        "npm run typecheck",
        "npm run test:coverage",
        "npm run build",
        "python-version: '3.11.15'",
        "python -m venv .ci-tools",
        "uv==0.11.32",
        "pip-audit==2.9.0",
        'UV_PROJECT_ENVIRONMENT="$PWD/.venv"',
        ".ci-tools/bin/uv sync --locked --extra dev",
        ".ci-tools/bin/pip-audit --local",
        ".ci-tools/bin/uv export --locked --no-dev --no-emit-project",
        ".ci-tools/bin/uv export --locked --extra dev --no-emit-project",
        '.ci-tools/bin/pip-audit --requirement "$runtime_requirements"',
        'mktemp -d "${RUNNER_TEMP}/weekly-cs-pytest.XXXXXX"',
        ".venv/bin/python -m compileall -q src/weekly_cs_report",
        '.venv/bin/pytest -q --basetemp "$pytest_basetemp" --cov=src/weekly_cs_report --cov-fail-under=85 --cov-report=json:"$RUNNER_TEMP/weekly-cs-python-coverage.json"',
        '.venv/bin/python scripts/check_python_coverage.py "$RUNNER_TEMP/weekly-cs-python-coverage.json" 85 80',
        "src/weekly_cs_report/langfuse_client.py",
        "src/weekly_cs_report/report.py",
        "src/weekly_cs_report/dashboard_cache.py",
        "src/weekly_cs_report/dashboard_schema.py",
        "src/weekly_cs_report/web.py",
        "npx playwright install --with-deps chromium",
        "npm run test:e2e",
    ):
        assert required in text

    assert text.index("python -m venv .ci-tools") < text.index("npm run test:e2e")
    assert text.index(".venv/bin/python -m compileall -q src/weekly_cs_report") < text.index(
        ".venv/bin/pytest -q --basetemp"
    )
    assert text.index(".venv/bin/pytest -q --basetemp") < text.index(
        ".venv/bin/python scripts/check_python_coverage.py"
    )
    assert "127.0.0.1:8765" not in text
    assert "uv lock" not in text
    assert "pip install -e '.[dev]'" not in text
    assert "pip-audit --local --skip-editable" not in text
    assert "npm install --global" not in text


def test_ci_requires_the_exact_locked_python_runtime_and_coverage_checker():
    text = _workflow()

    assert "sys.version_info[:3] == (3, 11, 15)" in text
    assert "sys.version_info[:2]" not in text
    assert "coverage.json" not in text.replace("$RUNNER_TEMP/weekly-cs-python-coverage.json", "")
    assert ".venv/bin/python scripts/check_python_coverage.py" in text


def test_generated_coverage_outputs_are_ignored_only_at_the_checkout_root():
    text = GITIGNORE.read_text(encoding="utf-8")

    assert "/frontend/coverage/" in text
    assert "/coverage.json" in text
    assert "/coverage-*.json" in text
    assert "\nfrontend/coverage/\n" not in text
    assert "\ncoverage.json\n" not in text
    assert "\ncoverage-*.json\n" not in text


def test_ci_pins_the_reviewed_pip_bootstrap_version():
    text = _workflow()
    install_prefix = (
        ".ci-tools/bin/python -m pip install --disable-pip-version-check \\\n"
    )

    assert text.count(install_prefix) == 1
    install_arguments = text.split(install_prefix, 1)[1].splitlines()[0].strip()
    assert install_arguments == (
        "--no-cache-dir 'pip==26.1.2' 'uv==0.11.32' 'pip-audit==2.9.0'"
    )
    assert "pip==26.2" not in text


def test_ci_accounts_for_the_single_locked_pytest_advisory_with_its_mitigation():
    text = _workflow()

    assert "PYSEC-2026-1845" in text
    assert "CVE-2025-71176" in text
    assert text.count("--ignore-vuln") == 1
    assert "--ignore-vuln PYSEC-2026-1845" in text
    assert "continue-on-error" not in text
    assert "dev_audit_status" in text
    assert 'test "$dev_audit_status" = "1"' in text
    assert (
        "'[.dependencies[].vulns[].id] | sort | join(\",\")'"
        in text
    )
    assert (
        "'[.dependencies[] | select(.vulns | length > 0) | .name]"
        " | unique | join(\",\")'"
        in text
    )
    assert 'test "$dev_vulnerability_ids" = "PYSEC-2026-1845"' in text
    assert 'test "$dev_vulnerable_packages" = "pytest"' in text
    assert 'test "$(stat -c \'%a\' "$pytest_basetemp")" = "700"' in text


def test_ci_validates_the_wheel_and_builds_the_runtime_image():
    text = _workflow()

    assert "scripts/build_wheel.sh dist/wheelhouse" in text
    assert 'PATH="$PWD/.ci-tools/bin:$PATH"' in text
    assert 'PYTHON_BIN="$PWD/.venv/bin/python"' in text
    assert "name: python-wheel" in text
    assert "path: dist/wheelhouse/*.whl" in text
    assert "if-no-files-found: error" in text
    assert "docker-build:" in text
    assert re.search(r"docker-build:\n(?:.*\n)*?    needs: quality", text)
    assert "docker build --pull --tag langfuse-weekly-cs-report:ci ." in text
    assert "docker run --detach" in text
    assert "http://127.0.0.1:18080/healthz" in text
    assert "http://127.0.0.1:18080/readyz" in text
    assert "http://127.0.0.1:18080/api/dashboard" in text
    assert "scripts.e2e_server import build_snapshot" in text
    assert "ProtectedSnapshotStore" in text
    assert "docker network create --internal" in text
    assert '--network "$network_name"' in text
    assert "X-Authenticated-User: ci-smoke" in text
    assert 'test "$unauthenticated_status" = "401"' in text
    assert 'test "$unauthenticated_api_status" = "401"' in text
