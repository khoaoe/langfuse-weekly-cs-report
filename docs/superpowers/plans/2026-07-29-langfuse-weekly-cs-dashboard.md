# Langfuse Weekly CS Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, validate, and demo a deterministic 12-week customer-service ticket analytics pipeline backed by session-level Langfuse scores and a native Langfuse Layered scorecard dashboard.

**Architecture:** A standalone Python package reads bounded Langfuse trace pages, selects weekday `turn0` cohorts, classifies ordered session lifecycles, loads observations only for the first transfer trace, applies a versioned taxonomy, and emits deterministic session and weekly score events. Writes use the Langfuse ingestion API with stable score IDs and Monday-noon score anchors, then poll V2 score readback before Computer Use creates native widgets.

**Tech Stack:** Python 3.9+, `dataclasses`, `zoneinfo`, `html.parser`, `httpx`, `python-dotenv`, `pytest`, Langfuse Public API v3.162.0, Computer Use.

## Global Constraints

- Project ID is exactly `cmqubjzur000hz507ptubh2l9`.
- Langfuse host is exactly `https://langfuse.zalopay.vn`.
- Business timezone is exactly `Asia/Ho_Chi_Minh`.
- Use exactly 12 completed Monday-Friday cohorts plus current WTD.
- Exclude weekend `turn0`; retain weekend follow-up turns.
- Use `sessionId`/`freshdesk_id` as ticket grain; never use trace count as ticket count.
- Survey is out of scope.
- Transfer matching is full-message equality after NFKC, case-folding, HTML entity decoding, tag stripping, and whitespace removal.
- Never infer transfer from `agents_used` alone.
- Score timestamps use Monday `12:00 Asia/Ho_Chi_Minh` (`05:00Z`), not local midnight.
- `reopen_within_7d` aggregate scores do not exist for immature weeks.
- A `207` ingestion response succeeds only when every requested event appears in `successes` and no event appears in `errors`.
- Never log credentials or raw ticket input/output.
- `artifacts/` uses directory mode `700`, file mode `600`, retains at most 30 runs, and contains no raw payloads.
- No real write occurs before dry-run gates and the canary/UI spike pass.
- The workspace is not a Git repository. Do not initialize one; use named task checkpoints instead of commits.
- Every Python module starts with `from __future__ import annotations` so the
  Python 3.9 runtime accepts the documented union and generic type syntax.

---

### Task 1: Package skeleton, models, and cohort time contract

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/weekly_cs_report/__init__.py`
- Create: `src/weekly_cs_report/models.py`
- Create: `src/weekly_cs_report/cohort.py`
- Create: `tests/test_cohort.py`

**Interfaces:**
- Produces:
  - `CohortWindow`
  - `TraceRecord`
  - `QualityIssue`
  - `SessionMetrics`
  - `TransferCategories`
  - `ScoreSpec`
  - `build_cohort_window(as_of: datetime, weeks: int, include_wtd: bool) -> CohortWindow`
  - `cohort_week_for(timestamp: datetime) -> date`
  - `score_anchor_for(cohort_week: date) -> datetime`
  - `is_week_fully_mature(cohort_week: date, as_of: datetime) -> bool`

- [x] **Step 1: Add installable package metadata**

Create `pyproject.toml` with this dependency contract:

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "langfuse-weekly-cs-report"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
  "httpx>=0.27,<1",
  "python-dotenv>=1,<2",
]

[project.optional-dependencies]
dev = [
  "pytest>=8,<9",
  "pytest-cov>=5,<7",
]

[project.scripts]
weekly-cs-report = "weekly_cs_report.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

Create `.venv` and install:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Expected: editable installation succeeds on Python 3.9.6.

- [x] **Step 2: Write failing cohort tests**

```python
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from weekly_cs_report.cohort import (
    build_cohort_window,
    cohort_week_for,
    is_week_fully_mature,
    score_anchor_for,
)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def test_window_has_twelve_complete_weeks_and_wtd():
    window = build_cohort_window(
        datetime(2026, 7, 29, 12, tzinfo=TZ),
        weeks=12,
        include_wtd=True,
    )
    assert window.complete_start_local == datetime(2026, 5, 4, 0, tzinfo=TZ)
    assert window.complete_end_exclusive_local == datetime(2026, 7, 27, 0, tzinfo=TZ)
    assert window.wtd_start_local == datetime(2026, 7, 27, 0, tzinfo=TZ)


def test_score_anchor_stays_in_monday_utc_bucket():
    anchor = score_anchor_for(date(2026, 7, 27))
    assert anchor == datetime(2026, 7, 27, 5, tzinfo=timezone.utc)
    assert anchor.weekday() == 0


def test_week_maturity_waits_until_last_friday_ticket_has_168_hours():
    assert not is_week_fully_mature(
        date(2026, 7, 20),
        datetime(2026, 7, 31, 22, 59, 59, tzinfo=TZ),
    )
    assert is_week_fully_mature(
        date(2026, 7, 20),
        datetime(2026, 7, 31, 23, 59, 59, 999999, tzinfo=TZ),
    )


def test_cohort_week_uses_vietnam_business_time():
    assert cohort_week_for(datetime(2026, 7, 26, 18, tzinfo=timezone.utc)) == date(2026, 7, 27)
```

- [x] **Step 3: Verify the tests fail**

Run:

```bash
.venv/bin/pytest tests/test_cohort.py -v
```

Expected: collection fails because `weekly_cs_report.cohort` does not exist.

- [x] **Step 4: Implement focused immutable models and cohort functions**

Use timezone-aware dataclasses. Reject naive datetimes with `ValueError`.
Define the maturity boundary as the end of cohort Friday plus exactly 168
hours. Define the score anchor as Monday `12:00` local converted to UTC.

Create these minimum model shapes:

```python
@dataclass(frozen=True)
class CohortWindow:
    as_of: datetime
    complete_start_local: datetime
    complete_end_exclusive_local: datetime
    wtd_start_local: datetime | None
    query_from_utc: datetime
    query_to_utc: datetime


@dataclass(frozen=True)
class TraceRecord:
    id: str
    session_id: str
    timestamp: datetime
    turn: int
    input_data: object
    output_data: object
    environment: str


@dataclass(frozen=True)
class QualityIssue:
    reason: str
    session_id: str | None
    trace_id: str | None
    timestamp: datetime | None


@dataclass(frozen=True)
class CategoryResult:
    value: str
    raw_values: tuple[str, ...] = ()
    source_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransferCategories:
    business: CategoryResult
    tpe: CategoryResult
    guardrail_rule: CategoryResult


@dataclass(frozen=True)
class SessionMetrics:
    session_id: str
    turn0_trace_id: str
    turn0_timestamp: datetime
    cohort_week: date
    score_timestamp: datetime
    cohort_status: str
    ai_first: bool
    no_ai_first_reason: str | None
    outcome: str | None
    reopen_lifetime: int | None
    reopen_within_7d: int | None
    ai_reply_count: int
    first_transfer_trace_id: str | None
    data_quality: str
    environment: str


@dataclass(frozen=True)
class ScoreSpec:
    id: str
    event_id: str
    name: str
    value: str | float
    data_type: str
    session_id: str
    timestamp: datetime
    environment: str
    metadata: dict[str, object]
```

- [x] **Step 5: Run the focused test**

```bash
.venv/bin/pytest tests/test_cohort.py -v
```

Expected: all Task 1 tests pass.

- [x] **Step 6: Record checkpoint**

Record: `task-1-cohort-contract-passed`.

---

### Task 2: Trace normalization and lifecycle classification

**Files:**
- Create: `src/weekly_cs_report/classification.py`
- Create: `tests/fixtures/traces.py`
- Create: `tests/test_classification.py`
- Modify: `src/weekly_cs_report/models.py`

**Interfaces:**
- Consumes: `CohortWindow`, `TraceRecord`, `SessionMetrics`, `QualityIssue`.
- Produces:
  - `normalize_transfer_text(value: object) -> str | None`
  - `is_transfer_response(output: object, canonical_text: str) -> bool`
  - `is_substantive_ai_response(output: object, canonical_text: str) -> bool`
  - `normalize_trace(raw: dict[str, object]) -> TraceRecord | QualityIssue`
  - `classify_session(traces: Sequence[TraceRecord], window: CohortWindow, canonical_text: str) -> SessionMetrics | QualityIssue`

- [x] **Step 1: Create synthetic, PII-free trace builders**

```python
def trace(
    trace_id: str,
    session_id: str | None,
    turn: object,
    timestamp: str,
    response: object,
    *,
    freshdesk_id: str | None = None,
    title: str = "IBFT synthetic",
) -> dict:
    return {
        "id": trace_id,
        "sessionId": session_id,
        "timestamp": timestamp,
        "environment": "default",
        "metadata": {"turn": turn},
        "input": {
            "source": "ticket",
            "other_info": {
                "freshdesk_id": freshdesk_id if freshdesk_id is not None else session_id,
                "title": title,
                "meta": {"domain": "ibft"},
                "comments": [],
            },
        },
        "output": {
            "response": response,
            "agents_used": ["customer-service"],
            "elapsed_s": 1.0,
        },
    }
```

- [x] **Step 2: Write failing transfer and lifecycle tests**

Test these exact cases:

```python
assert is_transfer_response({"response": TRANSFER_HTML}, TRANSFER_TEXT)
assert is_transfer_response({"response": TRANSFER_PLAIN_SOURCE}, TRANSFER_TEXT)
assert not is_transfer_response({"response": TRANSFER_TEXT + " thêm"}, TRANSFER_TEXT)
assert not is_transfer_response(
    {"response": "Giao dịch đang xử lý", "agents_used": ["customer-service"]},
    TRANSFER_TEXT,
)
```

Also assert:

- one AI `turn0` and no transfer is `ai_end_to_end`;
- later AI turns preserve `ai_end_to_end`;
- later transfer becomes `ai_then_cs`;
- transfer at `turn0` is `direct_cs`;
- immediate transfer has `ai_first=False` and `ai_reply_count=0`;
- any `turn>0` sets `reopen_lifetime=1` once;
- a later turn at exactly 168 hours sets `reopen_within_7d=1`;
- a later turn after 168 hours does not;
- the transfer response never increments AI reply count;
- Saturday/Sunday `turn0` is `weekend_start`, not an outcome;
- duplicate any turn number is `duplicate_turn`;
- missing or invalid turn is a quality issue;
- `sessionId != freshdesk_id` is `session_freshdesk_mismatch`;
- malformed output is unclassified rather than direct CS.

- [x] **Step 3: Verify failure**

```bash
.venv/bin/pytest tests/test_classification.py -v
```

Expected: classification symbols are missing.

- [x] **Step 4: Implement minimal deterministic classification**

Implementation rules:

```python
ordered = sorted(traces, key=lambda item: (item.turn, item.timestamp, item.id))
turn0 = next(item for item in ordered if item.turn == 0)
transfer_traces = [item for item in ordered if is_transfer_response(item.output_data, canonical)]
first_transfer = transfer_traces[0] if transfer_traces else None
ai_reply_count = sum(is_substantive_ai_response(item.output_data) for item in ordered)
```

Do not scan response substrings and do not use an agent name as a lifecycle
decision.

- [x] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_classification.py -v
```

Expected: all Task 2 tests pass.

- [x] **Step 6: Record checkpoint**

Record: `task-2-lifecycle-classification-passed`.

---

### Task 3: Versioned taxonomy and bounded transfer categories

**Files:**
- Create: `config/taxonomy.v1.json`
- Create: `src/weekly_cs_report/categories.py`
- Create: `tests/test_categories.py`

**Interfaces:**
- Consumes: turn0 raw input, observations from only the first transfer trace.
- Produces:
  - `Taxonomy`
  - `CategoryResult`
  - `load_taxonomy(path: Path) -> Taxonomy`
  - `classify_business(turn0_input: object, taxonomy: Taxonomy) -> CategoryResult`
  - `classify_tpe(observations: Sequence[dict], taxonomy: Taxonomy) -> CategoryResult`
  - `classify_guardrail(observations: Sequence[dict], taxonomy: Taxonomy) -> CategoryResult`
  - `classify_transfer(turn0: TraceRecord, observations: Sequence[dict], taxonomy: Taxonomy) -> TransferCategories`

- [x] **Step 1: Create the taxonomy contract**

Copy only code, step, case, and status from the 28-entry production fixture;
do not copy response messages. Include:

```json
{
  "version": "v1",
  "transfer": {
    "semantic_text": "Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận Chăm sóc Khách hàng.Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ."
  },
  "business": {
    "precedence": ["ibft", "topup", "withdraw", "oao"],
    "meta_keys": [
      "category", "type", "usecase", "domain", "intent",
      "loai", "loại", "phan_loai", "phân loại", "nghiep_vu", "nghiệp vụ"
    ],
    "max_meta_depth": 3,
    "patterns": {
      "ibft": ["ibft", "interbank", "inter-bank", "chuyen tien lien ngan hang", "lien ngan hang"],
      "topup": ["topup", "top up", "nap tien", "nap dt"],
      "withdraw": ["withdraw", "rut tien", "cashout", "cash out"],
      "oao": ["oao", "open account", "mo tai khoan"]
    },
    "fallback": "other"
  },
  "tpe": {
    "tool_names": [
      "get_transaction_processing_engine_data",
      "tool:get_transaction_processing_engine_data"
    ],
    "mappings": []
  },
  "guardrail": {
    "blocked_fields": ["blocked", "violation"],
    "passed_field": "passed",
    "value_fields": ["guardrail", "rule"]
  }
}
```

- [x] **Step 2: Write failing bounded-path tests**

Assert:

- business reads title and allowed meta keys only;
- comments, user input, user IDs, transaction IDs, and disallowed meta keys do
  not influence business category;
- two distinct business matches become `multiple`;
- no match becomes `other`;
- TPE reads only recognized tool observations;
- `transstatus` has priority, `stepresult` refines a mapped status;
- two distinct TPE results become `multiple`;
- no structured result becomes `unknown`;
- guardrail rule is accepted only with `blocked=true`, `passed=false`, or
  explicit truthy violation in the same observation;
- `guardrail_checks` and observation names alone are ignored.

- [x] **Step 3: Verify failure**

```bash
.venv/bin/pytest tests/test_categories.py -v
```

Expected: taxonomy and category symbols are missing.

- [x] **Step 4: Implement bounded extraction**

Use explicit dictionary access helpers and a depth-capped walk that yields only
values whose key is in `meta_keys`. Never serialize an entire input or
observation to text.

Define the immutable taxonomy container and validate the JSON schema while
loading:

```python
@dataclass(frozen=True)
class Taxonomy:
    version: str
    transfer_text: str
    business_precedence: tuple[str, ...]
    business_meta_keys: frozenset[str]
    business_patterns: dict[str, tuple[str, ...]]
    business_fallback: str
    max_meta_depth: int
    tpe_tool_names: frozenset[str]
    tpe_mappings: tuple[dict[str, object], ...]
```

The committed taxonomy must contain exactly the 28 production TPE mappings.
Add a test asserting `len(taxonomy.tpe_mappings) == 28`; generate the data
mechanically from the source fixture, then inspect the resulting diff before
running tests.

- [x] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_categories.py -v
```

Expected: all Task 3 tests pass.

- [x] **Step 6: Record checkpoint**

Record: `task-3-taxonomy-passed`.

---

### Task 4: Session selection, weekly aggregates, invariants, and quality gates

**Files:**
- Create: `src/weekly_cs_report/pipeline.py`
- Create: `tests/test_pipeline.py`
- Modify: `src/weekly_cs_report/models.py`

**Interfaces:**
- Consumes: normalized traces, cohort window, taxonomy, observation loader callback.
- Produces:
  - `CandidateSelection`
  - `AnalysisResult`
  - `GateStatus`
  - `select_candidate_sessions(records, issues, window) -> CandidateSelection`
  - `analyze_sessions(selection, taxonomy, observation_loader) -> AnalysisResult`
  - `summarize_weeks(result, window) -> tuple[WeeklySummary, ...]`
  - `evaluate_gates(result) -> GateStatus`
  - `validate_invariants(result) -> None`

- [x] **Step 1: Write failing selection and left-censor tests**

Create records containing:

- one valid weekday `turn0` with later weekend turns;
- one weekend `turn0`;
- one session with only `turn=3` because its `turn0` predates the fetch window;
- one invalid keyed session;
- one unkeyed trace.

Assert the five groups are disjoint and that `left_censored` and unkeyed traces
do not enter the ticket-grain structural denominator.

- [x] **Step 2: Write failing weekly summary tests**

Use a fixed cohort and assert:

```python
assert summary.ai_first_count == summary.ai_end_to_end_count + summary.ai_then_cs_count
assert summary.total_tickets == (
    summary.ai_end_to_end_count
    + summary.ai_then_cs_count
    + summary.direct_cs_count
    + summary.unclassified_count
)
```

For reply counts `[0, 1, 2, 10]`, nearest-rank output is:

```python
assert summary.ai_reply_p50 == 1
assert summary.ai_reply_p90 == 10
assert summary.ai_reply_max == 10
```

Assert an immature week has:

```python
assert summary.reopen_7d_rate is None
assert summary.reopen_7d_denominator is None
```

- [x] **Step 3: Write failing family-gate tests**

Assert:

- structural invalid rate above 5% blocks all families;
- business unknown above 20% blocks business only;
- both TPE and guardrail unknown above 50% blocks those two category families;
- core lifecycle, reopen, and reply families remain writable when only category
  gates fail.

- [x] **Step 4: Verify failure**

```bash
.venv/bin/pytest tests/test_pipeline.py -v
```

Expected: pipeline functions are missing.

- [x] **Step 5: Implement selection, summaries, and invariants**

Use nearest-rank:

```python
def nearest_rank(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]
```

Raise `InvariantError` before producing score specs when any reconciliation
equation fails.

Use these result containers:

```python
@dataclass(frozen=True)
class CandidateSelection:
    eligible: dict[str, tuple[TraceRecord, ...]]
    weekend_start: tuple[str, ...]
    left_censored: tuple[str, ...]
    invalid_keyed: tuple[QualityIssue, ...]
    unkeyed: tuple[QualityIssue, ...]


@dataclass(frozen=True)
class GateStatus:
    core_allowed: bool
    business_allowed: bool
    tpe_allowed: bool
    guardrail_allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WeeklySummary:
    cohort_week: date
    cohort_status: str
    total_tickets: int
    ai_first_count: int
    ai_first_rate: float
    ai_end_to_end_count: int
    ai_then_cs_count: int
    direct_cs_count: int
    unclassified_count: int
    reopen_7d_rate: float | None
    reopen_7d_denominator: int | None
    reopen_lifetime_rate: float | None
    ai_reply_p50: int | None
    ai_reply_p90: int | None
    ai_reply_max: int | None


@dataclass(frozen=True)
class AnalysisResult:
    sessions: tuple[SessionMetrics, ...]
    transfers: dict[str, TransferCategories]
    selection: CandidateSelection
    weekly: tuple[WeeklySummary, ...]
    gate_status: GateStatus
```

- [x] **Step 6: Run tests**

```bash
.venv/bin/pytest tests/test_pipeline.py -v
```

Expected: all Task 4 tests pass.

- [x] **Step 7: Record checkpoint**

Record: `task-4-analysis-passed`.

---

### Task 5: Langfuse read client and redacted failure handling

**Files:**
- Create: `src/weekly_cs_report/langfuse_client.py`
- Create: `tests/test_langfuse_client.py`

**Interfaces:**
- Produces class `LangfuseClient`:
  - `IngestionReceipt`
  - `LangfuseAPIError`
  - `IngestionPartialFailure`
  - `ScoreReadbackTimeout`
  - `iter_traces(from_timestamp: datetime, to_timestamp: datetime) -> Iterator[dict]`
  - `list_observations(trace_id: str) -> list[dict]`
  - `ingest_events(events: Sequence[dict]) -> IngestionReceipt`
  - `get_score(score_id: str) -> dict`
  - `wait_for_score(score_id: str, predicate: Callable[[dict], bool], timeout_s: float) -> dict`
  - `delete_score(score_id: str) -> None`

- [x] **Step 1: Write failing pagination tests with `httpx.MockTransport`**

Assert requests use:

```python
{
    "page": 1,
    "limit": 100,
    "fromTimestamp": "2026-05-04T00:00:00Z",
    "toTimestamp": "2026-07-29T05:00:00Z",
    "orderBy": "timestamp.asc",
    "fields": "core,io",
}
```

Return two mock pages and assert both are yielded exactly once.

- [x] **Step 2: Write failing observation tests**

Assert observation calls use V1:

```text
/api/public/observations?traceId=<id>&page=1&limit=100
```

and follow `meta.totalPages`.

- [x] **Step 3: Write failing `207` and polling tests**

Assert:

- a complete `207` receipt succeeds;
- a `207` containing any error raises `IngestionPartialFailure`;
- a missing event ID raises `IngestionPartialFailure`;
- `429` and `5xx` retry with bounded attempts;
- other `4xx` do not retry;
- `wait_for_score` polls V2 until the predicate passes or raises
  `ScoreReadbackTimeout`;
- exception strings never include auth values or response bodies.

- [x] **Step 4: Verify failure**

```bash
.venv/bin/pytest tests/test_langfuse_client.py -v
```

Expected: client module is missing.

- [x] **Step 5: Implement the client**

Use:

```python
self._client = httpx.Client(
    base_url=base_url.rstrip("/"),
    auth=(public_key, secret_key),
    timeout=httpx.Timeout(30.0),
    verify=True,
    transport=transport,
)
```

Read session scores only through `/api/public/v2/scores/{score_id}`.
Define redacted transport types explicitly:

```python
@dataclass(frozen=True)
class IngestionReceipt:
    requested_ids: tuple[str, ...]
    success_ids: tuple[str, ...]


class LangfuseAPIError(RuntimeError):
    pass


class IngestionPartialFailure(LangfuseAPIError):
    pass


class ScoreReadbackTimeout(LangfuseAPIError):
    pass
```

- [x] **Step 6: Run tests**

```bash
.venv/bin/pytest tests/test_langfuse_client.py -v
```

Expected: all Task 5 tests pass.

- [x] **Step 7: Record checkpoint**

Record: `task-5-client-passed`.

---

### Task 6: Deterministic session and weekly score events

**Files:**
- Create: `src/weekly_cs_report/scores.py`
- Create: `tests/test_scores.py`
- Modify: `src/weekly_cs_report/models.py`

**Interfaces:**
- Consumes: `SessionMetrics`, `WeeklySummary`, `GateStatus`.
- Produces:
  - `stable_score_id(project_id, analytics_version, taxonomy_version, subject_id, score_name) -> str`
  - `build_session_scores(metrics: SessionMetrics, categories: TransferCategories | None, gate_status: GateStatus, project_id: str, analytics_version: str, taxonomy_version: str) -> tuple[ScoreSpec, ...]`
  - `build_weekly_scores(summary: WeeklySummary, gate_status: GateStatus, project_id: str, analytics_version: str, taxonomy_version: str) -> tuple[ScoreSpec, ...]`
  - `score_to_event(spec: ScoreSpec) -> dict`
  - `chunk_events(events, max_events=100, max_bytes=3_000_000) -> Iterator[list[dict]]`

- [x] **Step 1: Write failing ID and update tests**

Assert:

- same score inputs produce the same score body ID;
- changing taxonomy version changes the score body ID;
- same canonical payload produces the same event ID;
- changed value produces a new event ID while body ID and timestamp remain
  unchanged;
- score timestamp is Monday `05:00Z`;
- session score body contains only `sessionId`, never `traceId`;
- metadata contains identifiers and evidence keys but no raw input/output.

- [x] **Step 2: Write failing score-eligibility tests**

Assert exact score families:

- every eligible ticket: `ai_first`, `ai_reply_count`,
  `ticket_data_quality`;
- `ai_first=0`: `no_ai_first_reason`;
- classified ticket: `ticket_outcome`;
- AI-first: `reopen_lifetime`;
- mature AI-first only: `reopen_within_7d`;
- transferred ticket: category scores allowed by the family gates;
- immature week: no `weekly_cs_reopen_7d_rate` and no denominator score.

- [x] **Step 3: Write failing chunk-size tests**

Create 205 small events and assert chunks are `100`, `100`, `5`. Create large
metadata values and assert every encoded `{"batch": chunk}` is below 3,000,000
bytes.

- [x] **Step 4: Verify failure**

```bash
.venv/bin/pytest tests/test_scores.py -v
```

Expected: score builders are missing.

- [x] **Step 5: Implement score builders**

Canonicalize payloads with:

```python
json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

Use UUIDv5 and include `project_id`, `analytics_version`,
`taxonomy_version`, subject, and score name in body IDs.

Make `score_to_event` the only conversion from `ScoreSpec` to ingestion JSON.
It must put `spec.timestamp` on the outer event and exactly one association,
`sessionId`, in the score body. Derive `event_id` from the complete canonical
event payload excluding `event_id` itself.

- [x] **Step 6: Run tests**

```bash
.venv/bin/pytest tests/test_scores.py -v
```

Expected: all Task 6 tests pass.

- [x] **Step 7: Record checkpoint**

Record: `task-6-score-events-passed`.

---

### Task 7: CLI orchestration and protected artifacts

**Files:**
- Create: `src/weekly_cs_report/cli.py`
- Create: `src/weekly_cs_report/artifacts.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_artifacts.py`
- Modify: `src/weekly_cs_report/pipeline.py`
- Modify: `README.md`

**Interfaces:**
- Produces commands:
  - `weekly-cs-report dry-run`
  - `weekly-cs-report sync --write`
  - `weekly-cs-report inspect-session SESSION_ID`
  - `weekly-cs-report canary`

- [ ] **Step 1: Write failing CLI configuration tests**

Assert:

- missing environment variables produce names only, never values;
- `dry-run` is the default command behavior;
- `sync` without `--write` exits non-zero before any POST;
- `--weeks` defaults to `12`;
- `--include-current-wtd` is supported;
- `--as-of` accepts an ISO timestamp for reproducible runs.

- [ ] **Step 2: Write failing artifact permission and retention tests**

Create 31 synthetic run directories and assert:

```python
assert stat.S_IMODE(latest_dir.stat().st_mode) == 0o700
assert stat.S_IMODE(report_file.stat().st_mode) == 0o600
assert len(run_directories) == 30
```

Assert serialized files contain no keys named `input`, `output`, `comments`,
`user_input`, `user_id`, `trans_id`, or `response`.

- [ ] **Step 3: Verify failure**

```bash
.venv/bin/pytest tests/test_cli.py tests/test_artifacts.py -v
```

Expected: CLI and artifact modules are missing.

- [ ] **Step 4: Implement orchestration**

The dry-run path must:

1. capture `as_of`;
2. fetch bounded traces;
3. normalize and select cohort sessions;
4. load observations only for first transfer traces;
5. classify, summarize, evaluate gates, and validate invariants;
6. write `summary.json`, `weekly_summary.csv`, `investigation.csv`, and
   `score_manifest.json`;
7. print a redacted, aggregate-only terminal summary.

The sync path repeats the same deterministic analysis, writes only allowed
families, ingests chunks, polls readback, and writes `reconciliation.json`.

Keep orchestration callable from tests through four concrete functions:
`run_dry_run(config: RunConfig, client: LangfuseClient) -> AnalysisResult`,
`run_sync(config: RunConfig, client: LangfuseClient, *, write: bool) ->
ReconciliationResult`, `build_parser() -> argparse.ArgumentParser`, and
`main(argv: Sequence[str] | None = None) -> int`. Task 7 is complete only when
the CLI tests exercise these paths end to end with fakes and no network access.

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_cli.py tests/test_artifacts.py -v
```

Expected: all Task 7 tests pass.

- [ ] **Step 6: Run the complete offline suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass without contacting Langfuse.

- [ ] **Step 7: Record checkpoint**

Record: `task-7-cli-passed`.

---

### Task 8: Real read-only dry run and manual classification audit

**Files:**
- Modify only when a defect is proven:
  - `config/taxonomy.v1.json`
  - focused source/test files

**Interfaces:**
- Consumes: target Langfuse read API and local `.env`.
- Produces: a protected dry-run artifact set with no external writes.

- [ ] **Step 1: Run real dry-run**

```bash
.venv/bin/weekly-cs-report dry-run \
  --weeks 12 \
  --include-current-wtd \
  --artifact-root artifacts
```

Expected: all trace pages load, invariants pass, and gate status is explicit.

- [ ] **Step 2: Inspect aggregate reconciliation**

Verify from `summary.json` and `weekly_summary.csv`:

```text
AI First = AI end-to-end + AI then CS
Total = three outcomes + unclassified
Reopen numerator <= denominator
Weekend-start and left-censored counts are excluded
```

- [ ] **Step 3: Audit at least 30 bounded ticket IDs**

Use `inspect-session` and source links, selecting tickets across all outcomes,
weekend follow-up, reopen, transfer, and data-quality groups. Do not copy raw
payloads into artifacts or terminal logs. Record only expected/actual labels
and source trace IDs in `manual_audit.csv`.

- [ ] **Step 4: Apply only evidence-backed corrections**

For every correction:

1. add a sanitized failing fixture;
2. run the focused test and observe failure;
3. change the minimal implementation/taxonomy;
4. rerun the focused and complete suite;
5. rerun the real dry-run.

- [ ] **Step 5: Record checkpoint**

Record: `task-8-real-dry-run-audited`.

---

### Task 9: Canary ingestion and native widget UI spike

**Files:**
- Modify only when a canary proves a contract mismatch:
  - `src/weekly_cs_report/langfuse_client.py`
  - `src/weekly_cs_report/scores.py`
  - corresponding tests

**Interfaces:**
- Consumes: real Langfuse write API and Computer Use.
- Produces: verified create/update/read/delete behavior and verified UI week
  bucket/widget capabilities.

- [ ] **Step 1: Run canary create and readback**

```bash
.venv/bin/weekly-cs-report canary --phase create
```

Expected: `207` receipt has one success, polling returns one session score with
value `0` and Monday `05:00Z`.

- [ ] **Step 2: Run canary update**

```bash
.venv/bin/weekly-cs-report canary --phase update
```

Expected: same body ID and timestamp, a new event ID, value becomes `1`, and V2
readback returns one logical score.

- [ ] **Step 3: Use Computer Use for UI spike**

In the target Langfuse widget editor:

1. select `Scores Numeric`;
2. filter score name to the canary score;
3. verify the point appears under the business `cohort_week`, not the prior week;
4. verify Big Number, Line, Histogram, P50, P90, and Max controls;
5. test long-form pivot legibility without saving a production widget.

If the UI bucket differs, stop bulk writing and correct only the score anchor.

- [ ] **Step 4: Delete the exact canary**

```bash
.venv/bin/weekly-cs-report canary --phase delete
```

Expected: DELETE queues successfully and bounded polling confirms the canary no
longer appears. No other score is deleted.

- [ ] **Step 5: Record checkpoint**

Record: `task-9-canary-ui-spike-passed`.

---

### Task 10: Real score sync, dashboard creation, and demo verification

**Files:**
- Modify: `README.md`
- Create: `artifacts/latest/dashboard_manifest.json` through the protected
  artifact writer

**Interfaces:**
- Produces the live dashboard `CS Agent — Weekly Ticket Outcomes`.

- [ ] **Step 1: Sync allowed score families**

```bash
.venv/bin/weekly-cs-report sync \
  --weeks 12 \
  --include-current-wtd \
  --write \
  --artifact-root artifacts
```

Expected:

- structural gate passes;
- core scores are ingested;
- category families write only when their own gates pass;
- every event is acknowledged;
- bounded readback reconciliation passes.

- [ ] **Step 2: Create native widgets with Computer Use**

Create and save:

1. total tickets;
2. AI First count and rate;
3. AI end-to-end;
4. AI then CS;
5. direct CS;
6. unclassified eligible tickets;
7. weekly stacked outcomes;
8. mature 7-day reopen line;
9. lifetime reopen line labelled dynamic;
10. reply-count histogram;
11. weekly P50;
12. weekly P90;
13. weekly maximum;
14. business transfer category when its gate passes;
15. TPE group when its gate passes;
16. guardrail/rule group when its gate passes;
17. data-quality status distribution.

Use `Past 90 days`, native weekly grouping, neutral titles, and descriptions that
state denominator/maturity rules.

- [ ] **Step 3: Assemble Layered scorecard dashboard**

Create `CS Agent — Weekly Ticket Outcomes`, arrange widgets in the approved
summary → trend → distribution → diagnosis → quality order, and set the
dashboard description to the latest `as_of` and any blocked category family.

- [ ] **Step 4: Verify visible numbers**

Compare at least:

- total tickets;
- AI First;
- three outcome counts;
- latest mature reopen rate;
- P50 and P90;
- each available transfer-category total;

against `weekly_summary.csv` and `reconciliation.json`.

Expected: native values reconcile or the affected widget is not handed off.

- [ ] **Step 5: Run final verification**

```bash
.venv/bin/pytest -v
.venv/bin/weekly-cs-report dry-run --weeks 12 --include-current-wtd
```

Expected: tests pass and dry-run reproduces the synchronized core metrics.

- [ ] **Step 6: Complete README handoff**

Document:

- install command;
- `.env` location and required variable names;
- dry-run, sync, inspect-session, and canary commands;
- metric definitions;
- gate behavior;
- dashboard URL;
- refresh is manual until a scheduler is explicitly added.

- [ ] **Step 7: Record checkpoint**

Record: `task-10-demo-verified`.
