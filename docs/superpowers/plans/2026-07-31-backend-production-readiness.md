# Backend Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: use
> `superpowers:test-driven-development` for every behavior change and
> `superpowers:verification-before-completion` before reporting.

**Goal:** Turn the current weekly CS dashboard backend into a verified
production candidate while explicitly deferring deployment.

**Architecture:** Preserve the current FastAPI + single-flight snapshot cache +
GET-only Langfuse client. Add one process-wide cancellation signal and one
monotonic refresh deadline, tighten the existing proxy-header boundary, emit
strict JSON operational events, make artifact writes atomic and symlink-safe,
and enforce the quality gates in CI.

**Tech stack:** Python 3.11.15, FastAPI, HTTPX, Uvicorn, pytest, pytest-cov,
standard-library logging and filesystem primitives.

## Global Constraints

- Deployment, Kubernetes, ingress, NetworkPolicy, PVC work, and a live rollout
  are out of scope.
- Preserve dashboard schema version 4 and the existing three browser API routes.
- Langfuse access remains GET-only; never add a write-shaped call.
- Keep the existing runtime dependency set; no new production package.
- Use one Uvicorn worker and one in-process refresh flight.
- Do not add a new authentication method. The proxy identity header remains the
  identity authority, and direct service isolation remains a deployment gate.
- Never log, return, or persist identities, request/query values, ticket IDs,
  trace IDs, observation IDs, credentials, raw upstream bodies, or exception
  messages.
- Do not change metric definitions, taxonomy behavior, cohort logic, the reopen
  LLM gate, or P0 coverage thresholds.
- Default full-refresh deadline is 120 seconds, valid range is 30 through 300.
- Default trace page limit is 500, valid range is 1 through 500.
- Uvicorn graceful-shutdown timeout is 45 seconds.
- Python total coverage must be at least 85%; each named critical backend file
  must be at least 80%.
- Every implementation task must finish with both its focused tests and the
  complete Python suite. The final verification repeats the full suite.
- Exact Python 3.11.15 execution is a CI gate. The current local `.venv` is
  Python 3.9.6, so local results must not be labeled exact-runtime verification
  unless a 3.11.15 interpreter is discovered and used.
- Follow RED -> verify expected failure -> GREEN -> refactor for every behavior
  change and preserve the evidence in the task report.
- This checkout contains user-owned uncommitted work. Do not stash, reset,
  clean, revert, stage, or commit. Do not edit files outside the task ownership
  list. The controller will create before/after review packages from exact file
  snapshots.

---

## Task 1: Bound and cancel the full refresh

**Ownership:**

- Modify: `src/weekly_cs_report/langfuse_client.py`
- Modify: `src/weekly_cs_report/report.py`
- Modify: `src/weekly_cs_report/dashboard_cache.py`
- Modify: `src/weekly_cs_report/web.py`
- Modify: `tests/test_langfuse_client.py`
- Modify: `tests/test_report.py`
- Modify: `tests/test_dashboard_cache.py`
- Modify: `tests/test_web.py`

**Required behavior:**

1. Add public, sanitized Langfuse exceptions for deadline exceeded, request
   cancelled, and trace page limit exceeded. They must carry only fixed method,
   path, and status-code values and remain mappable to
   `langfuse_unavailable`.
2. Extend `LangfuseClient.iter_traces` with keyword-only
   `deadline: float | None`, `cancel_event: threading.Event | None`, and
   `max_pages: int = 500`.
3. Validate `max_pages` as a non-boolean integer in `1..500`. Check cancellation
   before and after every page. Pass the shared deadline and cancellation event
   to `_request`. Reject an upstream `totalPages` greater than `max_pages`
   before yielding that page.
4. Replace private deadline/cancellation exceptions in request and retry paths
   with the public sanitized exceptions.
5. Extend `compute_report` with keyword-only
   `refresh_timeout_seconds: float = 120.0`,
   `max_trace_pages: int = 500`,
   `cancel_event: threading.Event | None = None`, and a monotonic clock seam.
   Calculate one full deadline; pass it into trace pagination. Calculate the
   exact enrichment deadline as
   `min(full_deadline - 5.0, refresh_start + 110.0)`. Check
   cancellation/deadline at report phase boundaries.
6. Give `SnapshotManager` an optional process-lifetime cancellation event and a
   monotonic clock seam. `close()` must set cancellation before waiting for the
   executor and remain idempotent.
7. Parse `DASHBOARD_REFRESH_DEADLINE_SECONDS` and
   `DASHBOARD_MAX_TRACE_PAGES` in production startup with the exact defaults and
   ranges from Global Constraints. Invalid values fail startup with sanitized
   fixed messages.
8. Pass the manager cancellation event and settings into `compute_report`.
   Configure `uvicorn.run(..., timeout_graceful_shutdown=45)`.
9. Preserve last-good snapshot, single-flight, manual cooldown, readiness, and
   partial-enrichment behavior.

**RED tests:**

- Trace pagination stops before page 501, rejects an advertised 501 pages before
  yielding, uses a reduced HTTP timeout near the deadline, and reacts to a set
  cancellation event without another request.
- A full report forwards the shared controls and fails with the sanitized
  deadline/cancellation type at phase boundaries.
- Manager close sets cancellation before its loader can exit.
- Startup rejects deadline/page values outside the exact ranges and passes
  valid values plus the 45-second Uvicorn option.

**Focused verification:**

```bash
.venv/bin/pytest -q tests/test_langfuse_client.py tests/test_report.py \
  tests/test_dashboard_cache.py tests/test_web.py
.venv/bin/pytest -q
```

---

## Task 2: Harden the proxy header and add privacy-safe JSON events

**Ownership:**

- Add: `src/weekly_cs_report/runtime_logging.py`
- Modify: `src/weekly_cs_report/dashboard_cache.py`
- Modify: `src/weekly_cs_report/web.py`
- Add: `tests/test_runtime_logging.py`
- Modify: `tests/test_dashboard_cache.py`
- Modify: `tests/test_web.py`

**Required behavior:**

1. In proxy mode, authenticate only one identity-header instance whose value is
   1..256 characters, unchanged by stripping, and contains no comma, whitespace,
   or ASCII control character. Continue to accept the current allowlisted
   header names. Never expose the value.
2. Keep health/readiness unprotected and root/API/assets protected.
3. Implement standard-library JSON event logging with an explicit event and
   field allowlist. Reject unsupported event names, field names, or non-scalar
   values rather than serializing arbitrary context.
4. Emit `snapshot_load_ignored`, `refresh_start`, `refresh_success`,
   `refresh_failure`, `refresh_cancelled`, `service_start`, and `service_stop`.
   Failure/cancellation logs use fixed codes only and never exception text.
5. Refresh success may log duration, schema version, ticket count, trace count,
   observation count, and aggregate coverage only when already available on the
   snapshot. It must not traverse or serialize ticket rows.
6. Keep Uvicorn access logging disabled.

**RED tests:**

- Duplicate, comma-delimited, padded, whitespace-containing, control-character,
  empty, and 257-character identity values all return the same fixed 401.
- A single valid header still authorizes the protected document, API, and
  assets.
- Every emitted line parses as one JSON object with only approved keys.
- A loader exception containing a fake secret, phone number, trace ID, and
  identity produces a fixed failure event containing none of them.
- Shutdown cancellation produces `refresh_cancelled`, not
  `refresh_failure`.

**Focused verification:**

```bash
.venv/bin/pytest -q tests/test_runtime_logging.py \
  tests/test_dashboard_cache.py tests/test_web.py
.venv/bin/pytest -q
```

---

## Task 3: Make protected artifacts atomic and symlink-safe

**Ownership:**

- Modify: `src/weekly_cs_report/artifacts.py`
- Modify: `tests/test_artifacts.py`

**Required behavior:**

1. Reject a symlink used as the store root, run directory, `latest` directory,
   or final JSON/CSV destination.
2. Write JSON and CSV to a same-directory temporary file with mode 0600, flush,
   fsync, and atomically replace the destination.
3. Clean temporary files after every failure.
4. Preserve forbidden-key checks, safe file-name checks, directory mode 0700,
   file mode 0600, `latest` publication, and 30-run retention.
5. Never modify the target of a rejected symlink.

**RED tests:**

- Root/run/latest/file symlinks are rejected and their targets stay unchanged.
- A serialization or replace failure leaves the previous artifact intact and
  no temporary file behind.
- Successful JSON and CSV commits remain mode 0600 and round-trip exactly.

**Focused verification:**

```bash
.venv/bin/pytest -q tests/test_artifacts.py
.venv/bin/pytest -q
```

---

## Task 4: Enforce Python coverage and CI runtime gates

### Task 4A: Remove unreachable Langfuse write/readback internals

The fresh coverage baseline is 90% overall, but the critical
`langfuse_client.py` module is only 69%. The uncovered bulk is legacy
ingestion/score implementation code that became unreachable when the production
client was made read-only. Do not hide this with exclusions or lower the gate.

**Ownership:**

- Modify: `src/weekly_cs_report/langfuse_client.py`
- Modify: `tests/test_langfuse_client.py`

Preserve the public fail-closed methods used by the deprecated CLI surface and
the `IngestionReceipt` type required for import compatibility. Remove only
private, unreferenced write/readback helpers and their unused exception/support
types. Add a regression test proving the client has no private score-readback
transport escape hatch, retain the explicit network allowlist tests, and use a
deliberate mutation to prove the new test detects reintroduction. Re-run the
focused test file, the full suite, and coverage. `langfuse_client.py` must reach
at least 80% without `pragma: no cover`, omitted files, or synthetic direct
tests of dead helpers.

### Task 4B: Wire the enforced gates

**Ownership:**

- Add: `scripts/check_python_coverage.py`
- Add: `tests/test_python_coverage_gate.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci_contract.py`
- Modify: `.gitignore`

**Required behavior:**

1. Build a standard-library coverage JSON checker. It accepts a coverage JSON
   path, minimum total percentage, minimum per-file percentage, and one or more
   critical suffixes. It fails closed for missing/malformed files, duplicate or
   unmatched suffixes, booleans/non-finite percentages, totals below 85, or a
   critical file below 80. Output contains file names and percentages only.
2. CI runs pytest with `pytest-cov`, writes a JSON report outside the repository
   worktree, enforces total 85, then runs the checker for:
   `langfuse_client.py`, `report.py`, `dashboard_cache.py`,
   `dashboard_schema.py`, and `web.py`.
3. Pin setup-python to exact `3.11.15` and assert the full
   `sys.version_info[:3]`.
4. Compile all package modules before tests with `python -m compileall -q`.
5. Preserve dependency audits, frontend gates, wheel validation, browser tests,
   and Docker smoke contract.
6. Ignore `frontend/coverage/` and generated coverage JSON.

**RED tests:**

- Checker passes exact boundary values and fails each malformed, missing,
  duplicate, unmatched, total-low, and file-low case.
- CI contract tests prove the exact version, compile step, coverage commands,
  thresholds, critical file list, and existing downstream gates.

**Focused verification:**

```bash
.venv/bin/pytest -q tests/test_langfuse_client.py
.venv/bin/pytest -q tests/test_python_coverage_gate.py tests/test_ci_contract.py
.venv/bin/pytest -q
```

---

## Task 5: Align the operating contract and release evidence

**Ownership:**

- Modify: `README.md`
- Modify: `docs/SPEC-v2.md`
- Add: `docs/superpowers/reports/2026-07-31-backend-production-readiness-report.md`
- Modify tests only if an existing documentation contract test fails because it
  asserts an obsolete schema/version statement.

**Required behavior:**

1. Document the two refresh environment variables, exact defaults/ranges,
   shutdown behavior, page ceiling, error semantics, and privacy-safe log event
   contract.
2. Document the strict proxy identity value rules and the unchanged requirement
   that only the authenticated proxy can reach the service.
3. Correct obsolete schema-v3 statements in SPEC-v2 to schema v4 and state that
   the packaged SPA supersedes the old inline-page delivery wording.
4. State that deployment is deferred and list the remaining deployment and
   secret-management gates.
5. Record local verification commands and results truthfully. Do not claim
   Docker or remote CI verification unless it actually ran.
6. Record the live P0 coverage evidence truthfully. Put two explicit,
   top-level machine-readable verdicts in the report:
   `backend_candidate=PASS|FAIL` and `go_live=PASS|BLOCKED`. A failing P0 gate
   keeps `go_live=BLOCKED`; it does not by itself change
   `backend_candidate=PASS` when every backend gate passed.

**Verification:**

```bash
.venv/bin/pytest -q
npm run typecheck
npm run test:coverage
npm run build
npm run test:e2e
```

The controller will additionally run compile, coverage, audits where locally
available, wheel validation, secret scanning, and an independent whole-change
review before declaring the plan complete.
