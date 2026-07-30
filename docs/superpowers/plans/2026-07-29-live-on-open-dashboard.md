# Live-on-open Weekly CS Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only internal dashboard service that checks Langfuse on every page open, refreshes a protected last-good snapshot when it is more than five minutes old, and exposes ticket IDs without exposing customer PII.

**Architecture:** A reusable report service calls the existing deterministic analytics pipeline. A browser-safe projection feeds an atomic five-minute cache with a single background refresh, and a same-origin FastAPI application serves the Layered scorecard plus a paginated ticket table. Langfuse credentials remain server-side, and deployment is a one-worker container behind the company VPN and authenticated reverse proxy.

**Tech Stack:** Python 3.9+, FastAPI, Uvicorn, `httpx`, `dataclasses`, `threading`, atomic filesystem replacement, vanilla HTML/CSS/JavaScript, `pytest`.

## Global Constraints

- Target project is exactly `cmqubjzur000hz507ptubh2l9`.
- Target host is exactly `https://langfuse.zalopay.vn`.
- Business timezone is exactly `Asia/Ho_Chi_Minh`.
- Use 12 completed Monday-Friday cohorts plus current WTD.
- The web service is read-only; it never writes Langfuse scores, traces, or observations.
- Cache TTL is exactly 300 seconds by default.
- Only one refresh may run in one service process.
- V1 runs exactly one Uvicorn worker.
- Ticket ID may be returned to authenticated internal viewers.
- User/account IDs, transaction IDs, phone numbers, names, emails, addresses, payment identifiers, conversation text, raw payloads, and trace/observation/score IDs must never enter browser payloads or persisted web snapshots.
- Browser payloads use explicit allowlists, never blacklist-based redaction.
- Runtime directories use mode `700`; protected snapshots use mode `600`.
- `.env` is never copied into a container image or sent to a browser.
- Production access requires VPN plus SSO/authenticated reverse proxy.
- The workspace is not a Git repository; record named checkpoints instead of commits.
- Every production-code change follows a witnessed failing test.

---

### Task 1: Correct the live structural-quality false positive

**Files:**
- Modify: `tests/test_classification.py`
- Modify: `src/weekly_cs_report/classification.py`

**Interfaces:**
- Consumes: `normalize_trace(raw: dict[str, object]) -> TraceRecord | QualityIssue`
- Produces: missing legacy `freshdesk_id` is accepted; two present, non-empty, different IDs still produce `session_freshdesk_mismatch`

- [ ] **Step 1: Add the missing-field regression test**

```python
def test_normalize_trace_allows_missing_legacy_freshdesk_id():
    raw = trace(
        "trace-1",
        "12345",
        0,
        "2026-07-20T02:00:00Z",
        "AI reply",
    )
    del raw["input"]["other_info"]["freshdesk_id"]

    result = normalize_trace(raw)

    assert isinstance(result, TraceRecord)
    assert result.session_id == "12345"
```

Keep the existing mismatch test and make it explicitly use two non-empty
different values.

- [ ] **Step 2: Run the focused test and witness the expected failure**

Run:

```bash
.venv/bin/pytest tests/test_classification.py::test_normalize_trace_allows_missing_legacy_freshdesk_id -v
```

Expected: FAIL because the current implementation returns
`session_freshdesk_mismatch`.

- [ ] **Step 3: Apply the minimum conditional fix**

Replace the current unconditional legacy-field requirement with:

```python
freshdesk_id = (
    other_info.get("freshdesk_id")
    if isinstance(other_info, Mapping)
    else None
)
if (
    isinstance(freshdesk_id, str)
    and freshdesk_id
    and freshdesk_id != session_id
):
    return _issue("session_freshdesk_mismatch", raw, timestamp)
```

Do not infer a ticket key from `freshdesk_id`; `sessionId` remains
authoritative.

- [ ] **Step 4: Run focused and full classification tests**

```bash
.venv/bin/pytest tests/test_classification.py -v
```

Expected: all classification tests pass.

- [ ] **Step 5: Record checkpoint**

Record `live-task-1-structural-gate-fixed`.

---

### Task 2: Bound guardrail categories to a browser-safe taxonomy

**Files:**
- Modify: `config/taxonomy.v1.json`
- Modify: `src/weekly_cs_report/categories.py`
- Modify: `tests/test_categories.py`

**Interfaces:**
- Extends `Taxonomy` with `guardrail_allowed_values: tuple[str, ...]`
- Produces `classify_guardrail(observations: Sequence[dict], taxonomy: Taxonomy) -> CategoryResult` whose public value is one of the configured labels, `multiple`, or `unknown`

- [ ] **Step 1: Add failing allowlist tests**

```python
def test_guardrail_returns_unknown_for_an_unapproved_value(taxonomy):
    result = classify_guardrail(
        [{"metadata": {"blocked": True, "rule": "customer-0901234567"}}],
        taxonomy,
    )
    assert result.value == "unknown"
    assert result.raw_values == ()
    assert result.source_fields == ()


def test_guardrail_keeps_an_approved_rule(taxonomy):
    result = classify_guardrail(
        [{"metadata": {"blocked": True, "rule": "max_replies_exceeded"}}],
        taxonomy,
    )
    assert result.value == "max_replies_exceeded"
```

Update configured-field tests to include the chosen allowed value.

- [ ] **Step 2: Run the focused tests and witness the leak**

```bash
.venv/bin/pytest \
  tests/test_categories.py::test_guardrail_returns_unknown_for_an_unapproved_value \
  tests/test_categories.py::test_guardrail_keeps_an_approved_rule -v
```

Expected: the first test fails because the arbitrary string is currently
returned as a category.

- [ ] **Step 3: Add the fixed V1 allowlist**

Add this field beneath `guardrail`:

```json
"allowed_values": [
  "cs_escalation",
  "empty_message_marker",
  "max_replies_exceeded",
  "missing_transaction_id",
  "prompt_injection_llm"
]
```

Make `load_taxonomy` require exactly the existing guardrail fields plus
`allowed_values`, parse it with `_string_list`, and store it on `Taxonomy`.

- [ ] **Step 4: Filter before constructing `CategoryResult`**

Inside `classify_guardrail`, append a value only when it is present in
`taxonomy.guardrail_allowed_values`. If no approved rule remains, return
`CategoryResult("unknown")`. Preserve `multiple` only for two or more distinct
approved rules.

- [ ] **Step 5: Run category and full offline tests**

```bash
.venv/bin/pytest tests/test_categories.py -v
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Record checkpoint**

Record `live-task-2-guardrail-allowlist-passed`.

---

### Task 3: Extract one reusable read-only report service

**Files:**
- Create: `src/weekly_cs_report/report.py`
- Create: `tests/test_report.py`
- Modify: `src/weekly_cs_report/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `LangfuseClient`
  - `build_cohort_window`
  - `normalize_raw_traces`
  - `select_candidate_sessions`
  - `analyze_sessions`
  - `validate_invariants`
- Produces:

```python
@dataclass(frozen=True)
class ReportRun:
    result: AnalysisResult
    taxonomy: Taxonomy
    traces_fetched: int
    traces_deduplicated: int


compute_report(
    client: LangfuseClient,
    *,
    as_of: datetime,
    weeks: int,
    include_current_wtd: bool,
    taxonomy_path: Path,
) -> ReportRun
```

- [ ] **Step 1: Write a failing report-service test**

Use the existing fake client and assert:

```python
run = compute_report(
    client,
    as_of=AS_OF,
    weeks=2,
    include_current_wtd=True,
    taxonomy_path=TAXONOMY_PATH,
)

assert run.traces_fetched == 3
assert run.traces_deduplicated == 3
assert [item.session_id for item in run.result.sessions] == [
    "ticket-ai",
    "ticket-transfer",
]
assert not (tmp_path / "artifacts").exists()
```

- [ ] **Step 2: Run the test and witness the missing module**

```bash
.venv/bin/pytest tests/test_report.py -v
```

Expected: collection fails because `weekly_cs_report.report` does not exist.

- [ ] **Step 3: Implement `ReportRun` and `compute_report`**

Move only the read-side sequence from `cli._execute_analysis`:

```python
window = build_cohort_window(as_of, weeks, include_current_wtd)
raw_traces = list(
    client.iter_traces(window.query_from_utc, window.query_to_utc)
)
records, issues, deduplicated_count = normalize_raw_traces(raw_traces)
selection = select_candidate_sessions(records, issues, window)
taxonomy = load_taxonomy(taxonomy_path)
result = analyze_sessions(selection, taxonomy, client.list_observations)
validate_invariants(result)
return ReportRun(
    result=result,
    taxonomy=taxonomy,
    traces_fetched=len(raw_traces),
    traces_deduplicated=deduplicated_count,
)
```

This function performs no artifact or Langfuse write.

- [ ] **Step 4: Make the CLI call the shared function**

Keep CLI score creation and protected artifact writing unchanged. Replace its
duplicated read pipeline with `compute_report`, then build scores and artifacts
from the returned `ReportRun`.

- [ ] **Step 5: Run report, CLI, and full tests**

```bash
.venv/bin/pytest tests/test_report.py tests/test_cli.py -v
.venv/bin/pytest -q
```

Expected: all tests pass and CLI artifact behavior is unchanged.

- [ ] **Step 6: Record checkpoint**

Record `live-task-3-shared-report-passed`.

---

### Task 4: Build the explicit browser-safe dashboard projection

**Files:**
- Create: `src/weekly_cs_report/dashboard_schema.py`
- Create: `tests/test_dashboard_schema.py`

**Interfaces:**
- Consumes: `ReportRun`
- Produces:

```python
@dataclass(frozen=True)
class TicketRow:
    ticket_id: str
    cohort_week: str
    cohort_status: str
    outcome: str
    ai_first: bool
    reopen_lifetime: int | None
    reopen_within_7d: int | None
    ai_reply_count: int
    business_category: str
    tpe_category: str
    guardrail_rule: str
    data_quality: str


@dataclass(frozen=True)
class DashboardSnapshot:
    generated_at: datetime
    dashboard: dict[str, object]
    tickets: tuple[TicketRow, ...]
```

- `DashboardSnapshot.dashboard_dict() -> dict[str, object]`
- `DashboardSnapshot.storage_dict() -> dict[str, object]`
- `DashboardSnapshot.from_storage_dict(value: Mapping[str, object]) -> DashboardSnapshot`
- `project_dashboard(run: ReportRun) -> DashboardSnapshot`
- `ticket_page(snapshot: DashboardSnapshot, *, cohort_week: str | None = None, outcome: str | None = None, business_category: str | None = None, tpe_category: str | None = None, guardrail_rule: str | None = None, ticket_id: str | None = None, page: int = 1, page_size: int = 50) -> dict[str, object]`

- [ ] **Step 1: Write failing privacy and ticket-retention tests**

Build a synthetic report containing:

- ticket ID `145665`;
- raw user ID `user-secret`;
- transaction ID `trans-secret`;
- phone `0901234567`;
- customer text in trace input/output;
- an approved guardrail label.

Assert:

```python
snapshot = project_dashboard(run)
encoded = json.dumps(snapshot.storage_dict(), ensure_ascii=False)

assert snapshot.tickets[0].ticket_id == "145665"
for forbidden in (
    "user-secret",
    "trans-secret",
    "0901234567",
    "customer message",
    "model response",
    "trace-1",
):
    assert forbidden not in encoded
```

Assert exact ticket-row keys:

```python
assert set(asdict(snapshot.tickets[0])) == {
    "ticket_id",
    "cohort_week",
    "cohort_status",
    "outcome",
    "ai_first",
    "reopen_lifetime",
    "reopen_within_7d",
    "ai_reply_count",
    "business_category",
    "tpe_category",
    "guardrail_rule",
    "data_quality",
}
```

- [ ] **Step 2: Run the projection tests and witness the missing module**

```bash
.venv/bin/pytest tests/test_dashboard_schema.py -v
```

Expected: collection fails because the projection module does not exist.

- [ ] **Step 3: Implement the projection from normalized models only**

Construct summary, weekly, transfer-distribution, source, gate, and
data-quality dictionaries from `AnalysisResult`, `WeeklySummary`, and approved
category values. Never traverse `TraceRecord.input_data`,
`TraceRecord.output_data`, observation dictionaries, `CategoryResult.raw_values`,
or `CategoryResult.source_fields`.

For ticket rows, use `SessionMetrics.session_id` as `ticket_id` and drop
`turn0_trace_id` and `first_transfer_trace_id`.

- [ ] **Step 4: Implement bounded filters and deterministic pagination**

Reject:

- `page < 1`;
- `page_size < 1` or `page_size > 100`;
- ticket IDs outside `[A-Za-z0-9_-]{1,64}`;
- outcomes outside `ai_end_to_end`, `ai_then_cs`, `direct_cs`,
  `unclassified`;
- invalid ISO cohort dates.

Sort by `(cohort_week, ticket_id)` and return:

```python
{
    "items": [asdict(row) for row in selected_rows],
    "page": page,
    "page_size": page_size,
    "total": total,
}
```

- [ ] **Step 5: Test storage round-trip and malformed storage rejection**

Round-trip `storage_dict()` through JSON and `from_storage_dict()`. Add an
unknown top-level field and assert `ValueError`, proving the disk format is
also allowlisted.

- [ ] **Step 6: Run focused and full tests**

```bash
.venv/bin/pytest tests/test_dashboard_schema.py -v
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Record checkpoint**

Record `live-task-4-browser-projection-passed`.

---

### Task 5: Add the atomic last-good cache and single-flight refresh

**Files:**
- Create: `src/weekly_cs_report/dashboard_cache.py`
- Create: `tests/test_dashboard_cache.py`

**Interfaces:**
- Consumes: `Callable[[], DashboardSnapshot]`
- Produces:

```python
@dataclass(frozen=True)
class CacheView:
    status: str
    snapshot: DashboardSnapshot | None
    refreshing: bool
    last_error_code: str | None
    last_error_at: datetime | None


```

- `ProtectedSnapshotStore(directory: Path)`
- `ProtectedSnapshotStore.load() -> DashboardSnapshot | None`
- `ProtectedSnapshotStore.save(snapshot: DashboardSnapshot) -> None`
- `SnapshotManager(loader: Callable[[], DashboardSnapshot], store: ProtectedSnapshotStore, *, ttl: timedelta = timedelta(seconds=300), clock: Callable[[], datetime] = utc_now)`
- `SnapshotManager.get() -> CacheView`
- `SnapshotManager.request_refresh(*, force: bool = False) -> CacheView`
- `SnapshotManager.wait_for_idle(timeout_seconds: float) -> bool`
- `SnapshotManager.close() -> None`

- [ ] **Step 1: Write failing first-boot and fresh-cache tests**

Assert first boot returns `loading` and starts one loader. After the loader
completes, repeated `get()` calls inside 300 seconds return `ready` without
additional calls.

- [ ] **Step 2: Run the tests and witness the missing module**

```bash
.venv/bin/pytest tests/test_dashboard_cache.py -v
```

Expected: collection fails because `dashboard_cache` does not exist.

- [ ] **Step 3: Implement one-worker background refresh**

Use `ThreadPoolExecutor(max_workers=1)` and a `threading.Lock`. The lock-protected
state owns the last-good snapshot, in-flight future, and sanitized failure
metadata. `get()` checks age and delegates stale work to
`request_refresh(force=False)`.

Map exceptions to fixed codes:

```python
if isinstance(error, LangfuseAPIError):
    code = "langfuse_unavailable"
elif isinstance(error, (ValueError, InvariantError)):
    code = "data_validation_failed"
else:
    code = "refresh_failed"
```

Do not store `str(error)`.

- [ ] **Step 4: Write and pass the concurrency test**

Release 20 threads through a barrier, call `manager.get()` in each, and assert
the blocking fake loader was invoked exactly once.

- [ ] **Step 5: Write and pass the last-good failure test**

Seed a valid snapshot, advance the fake clock past 300 seconds, make the loader
raise an exception containing a fake secret and phone number, and assert:

- the old snapshot remains present;
- status is `stale_error`;
- only the fixed error code is retained;
- neither secret nor phone number appears in `repr(manager.get())`.

- [ ] **Step 6: Implement protected atomic disk replacement**

Create the runtime directory with mode `700`. Serialize the allowlisted storage
dictionary into a same-directory temporary file with mode `600`, `flush`,
`os.fsync`, then `os.replace` it over `dashboard_snapshot.json`. Load through
`DashboardSnapshot.from_storage_dict`.

- [ ] **Step 7: Run cache and full tests**

```bash
.venv/bin/pytest tests/test_dashboard_cache.py -v
.venv/bin/pytest -q
```

Expected: all tests pass without deadlocks or leaked thread-pool warnings.

- [ ] **Step 8: Record checkpoint**

Record `live-task-5-cache-single-flight-passed`.

---

### Task 6: Serve authenticated same-origin dashboard APIs

**Files:**
- Create: `src/weekly_cs_report/web.py`
- Create: `tests/test_web.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `SnapshotManager`, `ticket_page`
- Produces:

```python
@dataclass(frozen=True)
class WebSettings:
    auth_mode: str
    identity_header: str


```

- `create_app(manager: SnapshotManager, *, settings: WebSettings) -> FastAPI`
- `main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: Add runtime dependencies and a failing API test**

Add:

```toml
"fastapi>=0.115,<1",
"uvicorn>=0.30,<1",
```

Add script:

```toml
weekly-cs-dashboard = "weekly_cs_report.web:main"
```

Install the editable package, then create an app with a fake ready manager and
assert `GET /api/dashboard` returns the projected aggregate.

- [ ] **Step 2: Run the API test and witness the missing module**

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest tests/test_web.py::test_dashboard_returns_ready_snapshot -v
```

Expected: collection fails because `weekly_cs_report.web` does not exist.

- [ ] **Step 3: Implement the API endpoints**

Implement:

- `GET /api/dashboard`: `200` with the last-good dashboard or `202` with
  `{"status": "loading"}`;
- `GET /api/tickets`: `200` paginated rows, or `503` when no snapshot exists;
- `POST /api/refresh`: request `force=True` and return `202`;
- `GET /healthz`: process health plus `has_snapshot`.

Add `Cache-Control: no-store` and `X-Content-Type-Options: nosniff` to `/api/*`
responses. Do not enable wildcard CORS.

- [ ] **Step 4: Implement and test proxy authentication**

`auth_mode="off"` is accepted only for the local command bound to
`127.0.0.1`. `auth_mode="proxy"` requires a non-empty configured identity
header on `/` and `/api/*`, otherwise returns `401` without identifying the
header value.

Tests assert:

- missing proxy identity is rejected;
- an identity value is accepted but never echoed in response JSON;
- `auth_mode="off"` with a non-loopback bind is rejected at startup.

- [ ] **Step 5: Implement strict query validation**

Convert `ValueError` from `ticket_page` to a fixed `422` response. Tests cover
page size `101`, invalid week, unsupported outcome, and malformed ticket ID.
Error bodies must name the invalid parameter but not echo its supplied value.

- [ ] **Step 6: Compose the production loader**

`main` must:

1. load the existing pinned Langfuse environment;
2. construct one `LangfuseClient`;
3. compute `as_of=datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))` inside each
   refresh, not at process startup;
4. call `compute_report(client, as_of=as_of, weeks=12, include_current_wtd=True, taxonomy_path=taxonomy_path)`;
5. call `project_dashboard`;
6. use a protected runtime directory outside static files;
7. close the manager and client on shutdown;
8. run exactly one Uvicorn worker.

- [ ] **Step 7: Run API, CLI, and full tests**

```bash
.venv/bin/pytest tests/test_web.py tests/test_cli.py -v
.venv/bin/pytest -q
.venv/bin/weekly-cs-dashboard --help
```

Expected: all tests pass and help prints without loading `.env`.

- [ ] **Step 8: Record checkpoint**

Record `live-task-6-web-api-passed`.

---

### Task 7: Convert the approved demo into a live frontend

**Files:**
- Create: `src/weekly_cs_report/static/index.html`
- Modify: `pyproject.toml`
- Create: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes:
  - `GET /api/dashboard`
  - `GET /api/tickets`
  - `POST /api/refresh`
- Produces: a self-contained same-origin dashboard with no embedded data or external resources

- [ ] **Step 1: Write failing static-contract tests**

Assert the packaged HTML:

- contains `/api/dashboard`, `/api/tickets`, and `/api/refresh`;
- contains no inline `const data={` snapshot;
- contains no `http://` or `https://`;
- contains no Langfuse key names;
- contains no sample user, transaction, phone, prompt, response, trace, or
  observation values;
- includes `aria-live`, visible keyboard focus, and a reduced-motion media
  query.

- [ ] **Step 2: Run the contract test and witness the missing file**

```bash
.venv/bin/pytest tests/test_frontend_contract.py -v
```

Expected: FAIL because the packaged live frontend does not exist.

- [ ] **Step 3: Port the Layered scorecard without embedded data**

Reuse the approved visual tokens and structure from
`artifacts/demo/weekly-cs-dashboard-demo.html`, but replace every data read with
safe DOM rendering from the API response. Keep all CSS and JavaScript local.
Declare the static directory as package data in `pyproject.toml`.

- [ ] **Step 4: Implement refresh-state behavior**

On load:

1. call `/api/dashboard`;
2. render the last-good data without clearing existing charts;
3. poll every two seconds while status is `loading` or `refreshing`;
4. stop fast polling when ready or stale-error;
5. repeat the freshness check every 300 seconds while the page remains open.

The **Làm mới ngay** button sends `POST /api/refresh`, disables while a refresh
is active, and resumes polling.

- [ ] **Step 5: Implement the ticket table**

Display:

- ticket ID;
- week;
- outcome;
- reopen;
- AI reply count;
- business, TPE, and guardrail/rule category;
- data-quality label.

Use server-side pagination, page sizes of 25/50/100, and the approved filters.
Render values with `textContent`, never `innerHTML`.

- [ ] **Step 6: Add precise freshness and failure copy**

Use:

- `Cập nhật lúc <local time>`;
- `Đang lấy dữ liệu mới từ Langfuse`;
- `Đang hiển thị dữ liệu gần nhất; lần cập nhật mới thất bại`;
- `Chưa có dữ liệu. Hệ thống đang thực hiện lần đọc đầu tiên`.

Never display upstream exception text.

- [ ] **Step 7: Run frontend and full tests**

```bash
.venv/bin/pytest tests/test_frontend_contract.py -v
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Record checkpoint**

Record `live-task-7-frontend-passed`.

---

### Task 8: Package a safe internal container and operating contract

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `tests/test_deployment_contract.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `weekly-cs-dashboard`
- Produces: one-worker port-8080 container that excludes local secrets and protected artifacts

- [ ] **Step 1: Write failing deployment-contract tests**

Assert:

- `.dockerignore` contains `.env`, `.venv`, `artifacts`, `runtime`, and
  `__pycache__`;
- `Dockerfile` never contains or copies `.env`;
- container command starts `weekly-cs-dashboard` on `0.0.0.0:8080`;
- worker count is exactly one;
- image runs as a non-root user.

- [ ] **Step 2: Run the test and witness missing files**

```bash
.venv/bin/pytest tests/test_deployment_contract.py -v
```

Expected: FAIL because the deployment files do not exist.

- [ ] **Step 3: Add the container**

Use `python:3.11-slim`, install the package, create an unprivileged
`dashboard` user, create `/app/runtime` owned by that user, expose `8080`, and
start:

```dockerfile
CMD ["weekly-cs-dashboard", "--host", "0.0.0.0", "--port", "8080"]
```

The non-local command must require `DASHBOARD_AUTH_MODE=proxy`.

- [ ] **Step 4: Document exact local and production commands**

README must include:

```bash
.venv/bin/weekly-cs-dashboard --local --port 8765
```

and a production environment contract naming only:

- `LANGFUSE_PUBLIC_KEY`;
- `LANGFUSE_SECRET_KEY`;
- `LANGFUSE_BASE_URL`;
- `DASHBOARD_AUTH_MODE=proxy`;
- `DASHBOARD_IDENTITY_HEADER`;
- `DASHBOARD_RUNTIME_DIR`.

Document that DevOps must provide the internal registry, runtime, domain,
TLS/SSO reverse proxy, and egress. Do not include credential examples.

- [ ] **Step 5: Run deployment and full tests**

```bash
.venv/bin/pytest tests/test_deployment_contract.py -v
.venv/bin/pytest -q
```

If Docker is available, also run:

```bash
docker build -t weekly-cs-dashboard:local .
```

If Docker is unavailable, report that image execution was not verified; do not
claim otherwise.

- [ ] **Step 6: Record checkpoint**

Record `live-task-8-container-contract-passed`.

---

### Task 9: Validate against real Langfuse and visually QA the live service

**Files:**
- Modify only when a witnessed failure requires a test-first fix
- Produce protected runtime snapshot under `runtime/`
- Update: `.superpowers/sdd/2026-07-29-langfuse-weekly-cs-dashboard/progress.md`

**Interfaces:**
- Consumes: real read-only Langfuse credentials in project `.env`
- Produces: verified local live dashboard and measured refresh behavior

- [ ] **Step 1: Run the complete offline suite**

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src tests
```

Expected: all tests pass with no warnings or errors.

- [ ] **Step 2: Run one real read-only cold refresh**

Start the local service:

```bash
.venv/bin/weekly-cs-dashboard --local --port 8765
```

Open `/api/dashboard`. Verify it first reports loading, then returns a protected
last-good snapshot. Record only:

- refresh duration;
- trace count;
- eligible ticket count;
- transfer count;
- gate status;
- aggregate distributions.

Do not record raw IDs or payloads in logs.

- [ ] **Step 3: Reconcile live metrics**

Compare the returned aggregate to a CLI read-only run at the same captured
`as_of`. Verify:

```text
AI First = ai_end_to_end + ai_then_cs
total = ai_end_to_end + ai_then_cs + direct_cs + unclassified
```

Verify the corrected structural gate has zero actual session/Freshdesk
mismatches for the audited data.

- [ ] **Step 4: Decide the guardrail presentation from evidence**

Measure the post-allowlist `multiple` share. If the raw cause cannot be
validated without exposing PII or the share remains implausibly high, keep the
guardrail section labelled `Provisional` and explain that it is not a reliable
root-cause distribution. Do not rename or merge categories without a separate
approved taxonomy change.

- [ ] **Step 5: Verify cache behavior**

Open the page twice inside five minutes and confirm the second open does not
start another Langfuse read. Trigger **Làm mới ngay** from two browser tabs and
confirm one refresh executes.

- [ ] **Step 6: Verify browser privacy**

Inspect `/api/dashboard`, one `/api/tickets` page, the static HTML, browser
network responses, and runtime snapshot. Confirm ticket IDs are present and
all prohibited identifiers/content are absent.

- [ ] **Step 7: Perform visual and interaction QA**

Check desktop and narrow mobile widths. Verify:

- charts and totals reconcile;
- refresh states do not blank data;
- filters and pagination work;
- keyboard focus is visible;
- no horizontal clipping;
- WTD and immature reopen labels are unambiguous.

- [ ] **Step 8: Run final verification**

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src tests
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS -I http://127.0.0.1:8765/
```

Expected: tests and compilation pass, health is successful, and the page is
served with safe headers.

- [ ] **Step 9: Record checkpoint and handoff**

Record `live-task-9-real-dashboard-verified`.

Hand off:

- local live URL;
- snapshot timestamp and measured refresh duration;
- verified privacy boundary;
- any provisional category family;
- the exact missing DevOps inputs that block a company-shareable URL.
