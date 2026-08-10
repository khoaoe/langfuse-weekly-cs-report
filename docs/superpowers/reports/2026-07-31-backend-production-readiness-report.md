backend_candidate=PASS
p0_data=FAIL
go_live=BLOCKED

# Backend production-readiness report — 2026-07-31

## Classification

**backend_candidate=PASS**. This is not a release or deployment approval.
**p0_data=FAIL**. The fixed-window raw Langfuse-only evidence is below both
hard thresholds: Issue Category `0.90` and TPE `0.85`. No narrower population
or local overlay is permitted.
**go_live=BLOCKED**. P0 data already blocks release. Deployment/Docker/ingress/
secrets/rollout/rollback gates also remain deferred or unverified. It is also
blocked by CS approval of the outcome labels, sheet-owner reconciliation, the
unperformed two-CS-user task test, and UXD/Brand/Design System 2.0
mapping/deviation acceptance. See the [production frontend release
gates](../specs/2026-07-30-zalopay-production-frontend-design.md#5-release-gates),
[SPEC-v2 §1.6](../../SPEC-v2.md#16-bộ-nhãn-chốt),
[SPEC-v2 §9.2](../../SPEC-v2.md#92-đối-soát-nghiệp-vụ--baseline-đo-được), and
[DESIGN status and deviations](../../../DESIGN.md#status).

## OBSERVED locally

The following evidence was observed in the local workspace:

- Fresh controller verification used Python `3.11.15`.
  `.venv/bin/python -m compileall -q src tests` and the full Python suite
  passed. Current Python total coverage is `90.27%`; critical-module coverage
  is `langfuse_client.py 81.61%`, `report.py 86.84%`,
  `dashboard_cache.py 90.29%`, `dashboard_schema.py 93.33%`, and `web.py
  92.73%`.
- Fresh frontend controller verification used Node `v24.18.0` and npm
  `11.16.0`: typecheck exited `0`; Vitest passed `17` files / `112` tests with
  coverage of statements `94.36%`, branches `87.63%`, functions `90.90%`, and
  lines `94.24%`; the production Vite build passed with `477` modules; and
  Playwright passed `105` tests with `31` skipped across `136` tests.
- The deterministic full Python suite used a fresh `mktemp -d` base confirmed
  `drwx------` (mode `0700`) with
  `uv run --isolated --extra dev --locked pytest -q --basetemp="$task2_basetemp"`.
  Task 2 did not modify shared `.venv`; this evidence does not infer its
  general dependency purity.
- Fresh frontend audits both exited `0` with `0` vulnerabilities:
  `npm audit --audit-level=low` and
  `npm audit --omit=dev --audit-level=low`.
- The locked Python runtime audit reported no known vulnerabilities. The locked
  test audit found exactly `pytest` / `PYSEC-2026-1845`; after the bounded
  `--ignore-vuln PYSEC-2026-1845`, it reported no other known vulnerabilities
  (`1` ignored). The test suite's private mode-`0700` base is the documented
  mitigation for that test-only advisory; this remains a bounded caveat, not a
  claim that the advisory is fixed.
- `scripts/build_wheel.sh` exited `0`, produced
  `langfuse_weekly_cs_report-0.1.0-py3-none-any.whl`, and validated parity for
  `14` static assets.
- An observed raw-only diagnostic rerun for the fixed window below used
  Langfuse traces only, printed one aggregate privacy-safe JSON object, and
  exited `0` in diagnostic mode. No credential value was read into this report
  or supplied on argv. The final current-source `--require-p0` rerun is still
  pending and is not claimed by this report revision.

This evidence satisfies the observed Python and frontend quality gates for the
production candidate. The P0 data failure, bounded test-only advisory, and
unobserved release gates below prevent a go-live claim.

### Raw Langfuse-only P0 diagnostic observed for 2026-07-31T10:00:00+07:00

Exact command:

```bash
.venv/bin/weekly-cs-report verify-dimensions --weeks 12 \
  --include-current-wtd --as-of 2026-07-31T10:00:00+07:00
```

Observed diagnostic exit: `0`.

Safe raw JSON P0 evidence:

```text
ticket_count = 6369
issue_category_present_count = 5393
coverage_issue_category = 0.8467577327680955
tpe_present_count = 5045
coverage_tpe = 0.7921180719108181
p0_issue_category_pass = false
p0_tpe_pass = false
p0_pass = false
```

Both measures use the complete raw root-ticket denominator. Valid sessions
count once; malformed keyed sessions and unkeyed ticket units remain in the
denominator. No source segment, entry point, category, or presence condition
may narrow it. Dashboard `coverage.tpe` remains a separate observation-source
measure.

Therefore this is a P0 data failure. For the same current source and fixed
window, the exact expected result with `--require-p0` is exit `1` after printing
the same one safe JSON object. A final current-source release-gate rerun remains
for the release owner to execute and record.

## CONFIGURED-ONLY or unobserved

- Docker image build/smoke behavior, deployed-environment browser smoke
  checks, remote GitHub Actions, and deployment behavior were not run or
  observed in this gate. No deploy or push occurred.
- [At least two CS users must complete the defined task test](../specs/2026-07-30-zalopay-production-frontend-design.md#5-release-gates).
  The concrete task is to find a prior-week ticket with more than four turns
  that was not transferred to CS, as specified in
  [SPEC-v2 §10](../../SPEC-v2.md#10-việc-ngoài-phạm-vi-code); this has not been
  performed.
- [UXD/Brand Owner and Design System acceptance](../../../DESIGN.md#status)
  has not been performed; the [unverified Design System mapping and open
  deviations](../../../DESIGN.md#deviations) remain release gates.
- [CS approval of the four outcome labels in SPEC-v2 §1.6](../../SPEC-v2.md#16-bộ-nhãn-chốt)
  has not been recorded. The current label contract is not a substitute for
  that approval.
- [Sheet-owner reconciliation required by SPEC-v2 §9.2 step 3](../../SPEC-v2.md#92-đối-soát-nghiệp-vụ--baseline-đo-được)
  has not been completed for any week that exceeds the stated AI First
  tolerance.
- Deployment remains deferred. The outstanding gates are proxy-only
  ingress/egress isolation, one-replica operation, production secret
  provisioning or rotation, PVC ownership and permissions, registry/image
  handling, remote CI and Docker evidence, and rollout/rollback proof.

## Operating contract recorded

- Refresh deadline: `DASHBOARD_REFRESH_DEADLINE_SECONDS`, default 120,
  inclusive 30..300 seconds. Trace page ceiling:
  `DASHBOARD_MAX_TRACE_PAGES`, default 500, inclusive 1..500, 100 traces per
  page. Enrichment deadline is `min(full_deadline - 5 seconds, refresh_start +
  110 seconds)`.
- Shutdown is cooperative: `SnapshotManager.close()` signals cancellation
  before executor join. The service uses one worker, a 45-second Uvicorn
  graceful-shutdown timeout, and disabled access logs.
- Fixed sanitized refresh errors preserve the last-good snapshot; optional
  enrichment may produce `enrichment_status: partial`. Allowed JSON runtime
  events are only `service_start`, `service_stop`, `snapshot_load_ignored`,
  `refresh_start`, `refresh_success`, `refresh_failure`, and
  `refresh_cancelled`; their fields are aggregate/fixed only, never identity,
  Ticket/trace ID, query, credential, raw upstream body, exception text, or
  URL. If durable snapshot storage cannot be read or validated during
  reconciliation, the service fails closed with `refresh_failed` and no
  in-memory snapshot until the PVC/filesystem is repaired.
- Proxy authentication accepts exactly one configured identity-header instance
  whose value is 1..256 characters and has no leading/trailing whitespace,
  comma, control character, or any whitespace. Only the authenticated proxy
  may reach the service; it must strip client-supplied identity headers before
  injecting its trusted value.
- Artifact JSON/CSV publication uses private atomic writes and rejects
  symlink components. Under the single-writer contract, a rename that completes
  then raises can retain a private recovery backup; no broader transactional
  guarantee is claimed.

## Verification commands, observed results, and pending P0 rerun

The code-quality commands and exits below were observed. The final P0 command
is explicitly marked pending.

```bash
.venv/bin/python -m compileall -q src tests
# exit 0; no output

task2_basetemp="$(mktemp -d)"
chmod 700 "$task2_basetemp"
coverage_report="$task2_basetemp/coverage.json"
uv run --isolated --extra dev --locked pytest -q \
  --basetemp="$task2_basetemp/pytest" \
  --cov=src/weekly_cs_report --cov-fail-under=85 \
  --cov-report=json:"$coverage_report"
# exit 0; total 90.27%
uv run --isolated --extra dev --locked python \
  scripts/check_python_coverage.py "$coverage_report" 85 80 \
  langfuse_client.py report.py dashboard_cache.py dashboard_schema.py web.py
# exit 0; all named critical modules >=80%

npm audit --audit-level=low
# exit 0; 0 vulnerabilities
npm audit --omit=dev --audit-level=low
# exit 0; 0 vulnerabilities

# Locked runtime audit: no known vulnerabilities.
runtime_audit_dir="$(mktemp -d)"
chmod 700 "$runtime_audit_dir"
uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file "$runtime_audit_dir/runtime.txt" --quiet
uvx --from pip-audit pip-audit --requirement "$runtime_audit_dir/runtime.txt"
# exit 0

# Locked test audit: first result exactly pytest/PYSEC-2026-1845; bounded ignore then no other finding.
test_audit_dir="$(mktemp -d)"
chmod 700 "$test_audit_dir"
uv export --locked --extra dev --no-emit-project --format requirements.txt --output-file "$test_audit_dir/test.txt" --quiet
uvx --from pip-audit pip-audit --requirement "$test_audit_dir/test.txt" --format json
# exit 1; exactly pytest/PYSEC-2026-1845
uvx --from pip-audit pip-audit --requirement "$test_audit_dir/test.txt" --ignore-vuln PYSEC-2026-1845
# exit 0; 1 ignored

final_wheel_dir="$(mktemp -d)"
PATH="$PWD/.ci-tools/bin:$PATH" PYTHON_BIN="$PWD/.venv/bin/python" \
  scripts/build_wheel.sh "$final_wheel_dir"
# exit 0; langfuse_weekly_cs_report-0.1.0-py3-none-any.whl; 14 static assets validated

# Pending final current-source release-gate rerun; not claimed as observed here.
.venv/bin/weekly-cs-report verify-dimensions --weeks 12 \
  --include-current-wtd --as-of 2026-07-31T10:00:00+07:00 --require-p0
# exact expected exit 1 from the current raw evidence; p0_pass=false
```

Task 2 did not alter shared `.venv`; this report makes no claim about its
current installed pytest or general dependency purity.
