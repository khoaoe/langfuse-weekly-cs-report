# Langfuse Weekly CS Dashboard Design

**Status:** Approved  
**Approval:** User approved the complete design on 2026-07-29 and delegated
subsequent design reviews through the first demo.  
**Target Langfuse project:** `cmqubjzur000hz507ptubh2l9`  
**Target dashboard:** `CS Agent — Weekly Ticket Outcomes`  
**Langfuse deployment:** `https://langfuse.zalopay.vn`, OSS v3.162.0

## 1. Objective

Build a repeatable, source-backed pipeline and a native Langfuse dashboard for
weekly customer-service ticket outcomes.

The unit of analysis is one ticket, represented by one Langfuse `sessionId`
equal to the Freshdesk ticket ID. A trace represents one turn, so raw trace
widgets cannot calculate lifecycle outcomes safely without session-level
derivation.

The dashboard must answer:

- How many tickets entered the agent?
- How many received a substantive AI response first?
- How many were handled by AI to the end?
- How many received AI help and were later transferred to CS?
- How many were transferred to CS immediately?
- How often did AI-first tickets reopen?
- How many substantive AI replies occurred per ticket?
- Which business, TPE, and guardrail/rule groups explain transfers?
- How much source data could not be classified reliably?

Customer survey is explicitly out of scope for V1.

## 2. Delivery Phases

### V1: deterministic analytics

V1 contains only deterministic rules, fixed taxonomies, data-quality checks,
Langfuse score ingestion, and native Langfuse widgets.

No LLM is used to count tickets, determine outcomes, calculate reopen rates, or
classify structured codes.

### V2: assisted root-cause classification

V2 may use an approved model only for unstructured causal classification of:

- reopen reasons;
- unusually long conversations;
- transfer reasons that remain `unknown`.

V2 is blocked until all of the following are available:

- an approved PII handling route;
- a fixed and versioned output taxonomy;
- a manually labelled evaluation set of approximately 50 tickets;
- accuracy and abstention thresholds;
- evidence links for every suggested label.

Low-confidence AI labels remain suggestions and do not replace V1 metrics.

## 3. Independent Project Boundary

The implementation lives in:

```text
langfuse-weekly-cs-report/
├── .env
├── .gitignore
├── README.md
├── pyproject.toml
├── config/
│   └── taxonomy.v1.json
├── src/
│   └── weekly_cs_report/
│       ├── __init__.py
│       ├── models.py
│       ├── cohort.py
│       ├── classification.py
│       ├── categories.py
│       ├── langfuse_client.py
│       ├── scores.py
│       ├── pipeline.py
│       └── cli.py
├── tests/
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

The project does not import from or depend at runtime on `cs-agent-master`.
Relevant production behavior may be checked against that repository during
development, but the analytics rules and taxonomy are copied into explicit,
versioned contracts here.

The `.env` file contains only:

- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_BASE_URL`

It is excluded by `.gitignore`, kept at mode `600`, and never printed.

## 4. Time and Cohort Contract

- Business timezone: `Asia/Ho_Chi_Minh`.
- A cohort week starts Monday at `00:00:00`.
- A ticket may enter a cohort only when its unique `turn=0` starts between
  Monday `00:00:00` and Friday `23:59:59.999999`.
- Tickets whose `turn=0` starts on Saturday or Sunday are excluded.
- Later turns on Saturday or Sunday remain part of lifecycle, outcome, transfer,
  and reopen calculations.
- V1 displays the latest 12 completed cohort weeks plus the current WTD cohort.
- `as_of` is captured once at the beginning of a run and used by every page and
  calculation in that run.
- API query timestamps are UTC; cohort decisions are made after conversion to
  `Asia/Ho_Chi_Minh`.

Derived score timestamps use a display anchor of cohort Monday at `12:00` in the
business timezone, converted to `05:00Z` for ingestion. Langfuse v3.162.0
calculates weekly buckets in UTC; using local midnight would become Sunday
`17:00Z` and could place a score in the previous week. The real `turn0`
timestamp and the business `cohort_week` date are retained in score metadata.

The canary UI spike must prove that the displayed weekly bucket matches
`cohort_week` before bulk ingestion.

## 5. Source Grain and Ordering

- `sessionId` is the ticket key and must equal `freshdesk_id`.
- Each trace represents one turn.
- `metadata.turn` is the authoritative turn number.
- A valid session has exactly one trace with `turn=0`.
- Traces are ordered by:
  1. numeric `metadata.turn`;
  2. timestamp;
  3. trace ID as a deterministic tie-breaker.

The following are data-quality conditions rather than normal outcomes:

- missing `sessionId`;
- missing `turn=0`;
- duplicate `turn=0`;
- non-numeric or negative turn;
- duplicate value for any `metadata.turn`;
- non-empty `sessionId` that differs from
  `input.other_info.freshdesk_id`;
- malformed output;
- contradictory transfer evidence.

No invalid session is forced into one of the three business outcomes.

### Left-censoring control

Trace fetching and session selection are separate phases:

1. fetch the bounded trace window from the oldest cohort Monday through the
   fixed `as_of`, in ascending timestamp order;
2. identify sessions that have one valid `turn0` inside the 12-week plus WTD
   cohort scope;
3. process every fetched later trace through `as_of` for only those sessions.

A session whose only fetched records are follow-up turns from a `turn0` before
the oldest cohort is `out_of_scope_left_censored`. It is excluded from business
metrics and from the structural quality-rate gate. It remains visible as a
separate diagnostic count.

## 6. Transfer Detection

The authoritative deployed transfer response is:

```html
<p>Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận Chăm sóc Khách hàng.</p><p>Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ.</p>
```

The production source was checked for this default message. The checked-in
source currently builds the same two sentences as adjacent plain-text literals,
while observed Langfuse output stores them as two `<p>` blocks. The analytics
project remains independent and stores both the canonical semantic text and the
expected HTML representation in its own versioned configuration.

Representation normalization is deliberately narrow:

1. coerce the response to a string only when it is already a scalar string;
2. normalize Unicode to NFKC and apply `casefold`;
3. decode HTML entities;
4. strip HTML tags without retaining markup attributes;
5. remove Unicode whitespace;
6. compare the entire normalized semantic text for equality with the canonical
   two-sentence transfer text.

The detector does not:

- use substring matching;
- use fuzzy matching;
- classify solely from `agents_used=["customer-service"]`.

Plain text and the expected two-`<p>` HTML representation therefore match only
when they normalize to the complete canonical message. Partial text or extra
customer-facing prose does not match.

`agents_used` is corroborating evidence only. A customer-service agent marker
without the canonical transfer response is reported as a data-quality mismatch.

## 7. Substantive AI Response

A trace has a substantive AI response when all of these are true:

- `output.response` is a non-empty string after trimming;
- it is not the canonical transfer response;
- it is not explicitly identified as a guardrail/rule-only block;
- the output is not malformed or a known technical placeholder.

The label “no response” is avoided because an immediate CS transfer still emits
a customer-facing transfer message.

When `turn0` has no substantive AI response, `no_ai_first_reason` is one of:

- `direct_cs`;
- `guardrail_rule`;
- `empty_or_technical`;
- `unknown`.

## 8. Mutually Exclusive Ticket Outcomes

The three normal lifecycle outcomes are:

- `ai_end_to_end` — **AI xử lý đến cuối**: `turn0` has a substantive AI
  response and no later trace has the canonical transfer response.
- `ai_then_cs` — **AI hỗ trợ trước, CS tiếp quản**: `turn0` has a substantive AI
  response and at least one later trace has the canonical transfer response.
- `direct_cs` — **CS tiếp quản ngay**: the `turn0` response is the canonical
  transfer response.

A valid `turn0` that fits none of these outcomes is `unclassified` for reporting
and receives an explicit data-quality reason. It is not silently assigned to a
business outcome.

Derived invariant:

```text
AI First = ai_end_to_end + ai_then_cs
```

Outcome is evaluated as of the run time. A later transfer may change an earlier
`ai_end_to_end` ticket into `ai_then_cs`, so reruns must update existing scores.

## 9. Reopen Metrics

### `reopen_lifetime`

For an AI-first ticket:

```text
1 when any trace has metadata.turn > 0
0 otherwise
```

This is an operational, dynamic value as of the run time.

### `reopen_within_7d`

For an AI-first ticket:

```text
1 when a trace with metadata.turn > 0 occurs at
0 < trace_timestamp - turn0_timestamp <= 168 hours
0 otherwise
```

Each ticket contributes at most once.

For week-over-week comparison, a cohort week is included only after every
ticket in that Monday-Friday cohort has had the full 168-hour observation
window. Partially mature weeks are excluded from the benchmark widget rather
than using a biased partial denominator.

The numerator and denominator are both retained in weekly aggregate metadata.

## 10. AI Reply Count

`ai_reply_count` is the number of traces in the session containing a substantive
AI response. The canonical transfer response is excluded.

The score is written for every cohort-eligible ticket:

- immediate CS transfer contributes `0`;
- technical/unclassified tickets may contribute `0`;
- later AI replies count even if a later trace transfers to CS.

The dashboard emphasizes:

- distribution histogram;
- P50;
- P90;
- maximum.

Average is secondary because it can conceal a long tail.

Weekly P50 and P90 aggregate scores use the deterministic nearest-rank method:
sort integer reply counts ascending and select rank `ceil(p * n)`, using
one-based ranks. Empty cohorts emit no percentile score.

## 11. Transfer Classification

Only bounded sources are used for transfer classification:

- business category may use `turn0` input metadata and structured fields from
  the first transfer trace;
- TPE and guardrail/rule groups use observations from the first transfer trace
  only;
- the ordered session sequence is used only to locate that first transfer.

A ticket is counted once in each independent dimension.

### Business category

Fixed V1 values:

- `ibft`
- `topup`
- `withdraw`
- `oao`
- `other`
- `unknown`
- `multiple`

### TPE group

Resolution order and allowed JSON paths:

1. select an observation only when
   `metadata.tool_name == "get_transaction_processing_engine_data"` or
   `name == "tool:get_transaction_processing_engine_data"`;
2. read only `output.result.tpe_error_code` or
   `output.result.transstatus` as the primary code;
3. read only `output.result.stepresult` as fallback;
4. `unknown`.

Multiple distinct supported codes produce `multiple`; raw codes are retained in
metadata.

### Guardrail/rule group

Only these explicit fields are inspected:

- `output.blocked`
- `output.passed`
- `output.rule`
- `output.guardrail`
- `metadata.blocked`
- `metadata.passed`
- `metadata.rule`
- `metadata.guardrail`
- `metadata.violation`

A rule is accepted only when the same observation shows `blocked=true`,
`passed=false`, or a truthy explicit violation. Observation names and
`metadata.guardrail_checks` alone do not prove that a guardrail caused transfer.

No explicit evidence produces `unknown`. Multiple distinct explicit rule values
produce `multiple`.

Every score includes `taxonomy_version=v1`.

## 12. Taxonomy Contract

`config/taxonomy.v1.json` is the sole runtime taxonomy for V1.

It contains:

- canonical transfer HTML;
- business-category keywords and precedence;
- TPE code mappings;
- `stepresult` fallback mappings;
- guardrail/rule mappings;
- technical placeholder markers;
- explicit allowed output values.

Business classification reads only:

- `turn0.input.other_info.title`;
- values under `turn0.input.other_info.meta` whose key appears in the configured
  business-key allowlist, with traversal capped at depth three.

It never scans comments, user input, user IDs, Freshdesk IDs, transaction IDs,
or arbitrary recursive payload content for keywords. Allowed paths and key
precedence are fixture-tested.

Unknown values remain visible. A taxonomy change requires:

1. a new taxonomy version;
2. fixture updates;
3. regression tests;
4. a controlled historical rebuild.

## 13. Session-Level Score Contract

| Score name | Type | Eligibility | Values |
| --- | --- | --- | --- |
| `ai_first` | Numeric | Every cohort-eligible ticket | `0`, `1` |
| `no_ai_first_reason` | Categorical | `ai_first=0` | Defined reasons |
| `ticket_outcome` | Categorical | Normally classified tickets | Three outcomes |
| `reopen_lifetime` | Numeric | AI-first tickets | `0`, `1` |
| `reopen_within_7d` | Numeric | AI-first tickets in fully mature weeks | `0`, `1` |
| `ai_reply_count` | Numeric | Every cohort-eligible ticket | Integer `>=0` |
| `ticket_data_quality` | Categorical | Every session with usable `sessionId` | `valid` or primary issue |
| `transfer_business_category` | Categorical | Transferred tickets | V1 categories |
| `transfer_tpe_group` | Categorical | Transferred tickets | Mapped group, `unknown`, `multiple` |
| `transfer_guardrail_rule` | Categorical | Transferred tickets | Mapped rule, `unknown`, `multiple` |

Common metadata:

- `analytics_version`
- `taxonomy_version`
- `session_id`
- `turn0_trace_id`
- `turn0_timestamp`
- `cohort_week`
- `cohort_status` (`complete` or `wtd`)
- `as_of`
- `first_transfer_trace_id` when applicable
- `transfer_mode` when applicable
- classification source fields
- raw structured codes when values are `unknown` or `multiple`

Metadata never contains raw comments, titles, descriptions, customer contact
details, or complete response content.

## 14. Weekly Aggregate Score Contract

Weekly aggregate scores support native Langfuse pivot tables and ensure that
metrics with different aggregations remain comparable.

Each week uses synthetic session ID:

```text
weekly-cs-summary:<YYYY-MM-DD>
```

Aggregate score names:

- `weekly_cs_total_tickets`
- `weekly_cs_ai_first_count`
- `weekly_cs_ai_first_rate`
- `weekly_cs_ai_end_to_end_count`
- `weekly_cs_ai_then_cs_count`
- `weekly_cs_direct_cs_count`
- `weekly_cs_unclassified_count`
- `weekly_cs_reopen_7d_rate`
- `weekly_cs_reopen_7d_denominator`
- `weekly_cs_reopen_lifetime_rate`
- `weekly_cs_ai_reply_p50`
- `weekly_cs_ai_reply_p90`
- `weekly_cs_ai_reply_max`

One score exists per eligible metric per cohort week. The two 7-day-reopen
aggregate scores are omitted entirely until that week is fully mature.
Aggregate metadata contains numerator, denominator, cohort maturity, session
count, and run time where applicable.

## 15. Idempotent Score Ingestion

The implementation uses Langfuse ingestion events so the score timestamp can be
backdated to the cohort Monday display anchor at `12:00 Asia/Ho_Chi_Minh`.

Score body IDs are deterministic UUIDv5 values based on:

```text
project_id | analytics_version | taxonomy_version | subject_id | score_name
```

Event envelope IDs are deterministic UUIDv5 values based on:

```text
score_id | canonical_payload_hash
```

Consequences:

- an identical rerun is ignored safely;
- a changed outcome creates a new ingestion event;
- the stable score body ID updates the existing score instead of duplicating it;
- the score name and cohort timestamp remain unchanged.

Before bulk ingestion:

1. create a reserved canary session score;
2. read it back;
3. update its value with the same score ID;
4. read it back again;
5. delete the exact canary score;
6. stop if any step disagrees with expected behavior.

Bulk ingestion is batched to at most 100 events and less than 3 MB encoded
payload per request. Langfuse may return HTTP `207` after accepting an
ingestion batch asynchronously, so every per-event result is inspected and
readback is polled with a bounded timeout. Only HTTP `429` and `5xx` responses
are retried with bounded exponential backoff. Validation and other `4xx`
responses stop the run.

After writing, the pipeline reads scores back and reconciles counts and values
against the local manifest. A failed reconciliation leaves a rerunnable manifest
and does not delete unrelated Langfuse data.

## 16. Data-Quality Gates

Every normal run begins as a dry run. Gates apply at the metric-family level:

- more than 5% structurally invalid keyed candidate sessions blocks all score
  families;
- more than 20% business `unknown` among transferred tickets blocks only
  `transfer_business_category`;
- more than 50% of transferred tickets have both TPE and guardrail dimensions
  `unknown`, which blocks only `transfer_tpe_group` and
  `transfer_guardrail_rule`.

The structural denominator is ticket-grain:

```text
distinct non-empty sessionId values in or potentially entering cohort scope
```

Unkeyed traces cannot be deduplicated reliably at ticket grain. They are reported
as `unkeyed_trace_count` but are not added to the ticket-grain structural rate.
The report keeps these non-overlapping counts separate:

- `eligible_ticket_count`;
- `unclassified_eligible_count`;
- `invalid_keyed_session_count`;
- `unkeyed_trace_count`;
- `weekend_start_count`;
- `left_censored_count`.

The dry-run report includes:

- traces fetched and deduplicated;
- candidate and eligible sessions;
- weekday and weekend-start counts;
- outcome distribution;
- AI-first distribution;
- reopen numerator and denominator;
- reply-count distribution;
- transfer-category coverage;
- `unknown` and `multiple` coverage;
- every data-quality reason;
- source trace IDs for investigation.

Reports are written beneath ignored `artifacts/` and contain identifiers and
classification evidence fields only, not raw PII-bearing content.

## 17. Native Langfuse Dashboard

The selected layout is **Layered scorecard**:

1. source status and maturity;
2. primary outcomes;
3. weekly movement;
4. reply distribution;
5. transfer diagnosis;
6. data quality and traceability.

The dashboard uses the native `Past 90 days` range. Because analytical score
timestamps are cohort Mondays, this gives 12 completed weeks plus WTD without
splitting individual cohort weeks.

### Status

Langfuse v3.162.0 does not expose score metadata as a dashboard dimension and
does not provide an automated markdown status card. Therefore:

- the dashboard description records the latest pipeline `as_of`;
- widget descriptions state the maturity and WTD rules;
- the local run summary contains exact freshness and quality-gate status;
- attributes that require grouping are represented as score names or values,
  never assumed to be filterable metadata.

### KPI and outcome widgets

- Total tickets.
- AI First count and rate.
- AI handled to end.
- AI then CS.
- Direct CS.
- Unclassified eligible-ticket count.
- Weekly stacked outcome chart.

### Reopen widgets

- Weekly `reopen_within_7d` rate for fully mature weeks only.
- Weekly `reopen_lifetime` rate labelled dynamic/as-of.

### Reply widgets

- Histogram of session-level `ai_reply_count`.
- Weekly P50.
- Weekly P90.
- Weekly maximum.

### Transfer widgets

- Business category.
- TPE code/stepresult group.
- Guardrail/rule group.

### Comparison tables

The UI canary tests the available pivot behavior on the actual deployment before
bulk ingestion. The native dashboard will use a long-form weekly comparison
table only if the score-name/time dimensions render legibly. Otherwise the
authoritative weekly comparison table is generated as
`artifacts/latest/weekly_summary.csv`, while the same metrics remain charted in
native widgets. A wide mixed-unit pivot is not assumed to be supported.

### Data quality

- Data-quality status distribution.
- Unknown/multiple coverage.
- IDs and source trace links remain available through the local investigation
  artifact. Langfuse v3.162.0 score widgets do not expose session-level
  drill-down consistently, so that capability is not assumed.

## 18. CLI Contract

Required commands:

```text
weekly-cs-report dry-run --weeks 12 --include-current-wtd
weekly-cs-report sync --weeks 12 --include-current-wtd --write
weekly-cs-report inspect-session <session-id>
weekly-cs-report canary
```

Safety rules:

- `dry-run` is the default behavior;
- external writes require the explicit `--write` flag;
- the CLI prints only redacted configuration state;
- TLS verification remains enabled;
- no command deletes traces, observations, or unrelated scores.

`artifacts/` directories are mode `700`, files are mode `600`, and only the 30
latest run directories are retained. Artifacts contain no raw payloads.

V1 is a repeatable CLI and does not install a scheduler. A daily or weekly
scheduler is a separate deployment decision.

## 19. Testing Strategy

### Unit tests

- exact normalized canonical transfer HTML;
- the exact source plain-text representation matches after representation
  normalization;
- partial transfer wording does not match;
- extra prose before or after the canonical HTML does not match;
- customer-service agent marker without canonical HTML does not transfer;
- AI end-to-end with one or many later AI turns;
- AI then CS;
- direct CS;
- unclassified technical output;
- weekend-start exclusion;
- Friday start with weekend or next-week outcome;
- reopen at, before, and after the 168-hour boundary;
- each ticket reopens at most once;
- AI reply count excludes transfer response;
- missing, duplicate, invalid turn data;
- `sessionId`/`freshdesk_id` mismatch;
- left-censored sessions do not enter quality gates or KPI denominators;
- taxonomy precedence, `unknown`, and `multiple`;
- first-transfer-trace-only classification;
- deterministic score and event IDs;
- score update when lifecycle changes.

### Client tests

- pagination;
- trace reads use `page`, `limit<=100`, inclusive `fromTimestamp`, exclusive
  `toTimestamp`, ascending timestamp order, and bounded response fields;
- UTC timestamp serialization;
- HTTP `207` per-event result handling and bounded readback polling;
- HTTP `207` partial failure never reports a successful sync;
- retry only on `429` and `5xx`;
- no retry on validation `4xx`;
- redacted errors;
- ingestion batching;
- readback reconciliation.

### Integration tests

- all network tests use a fake HTTP transport by default;
- real Langfuse testing is limited to the named canary workflow;
- no unit or normal integration test writes to the real project.

### Manual acceptance sample

Review at least 30 tickets across:

- all three normal outcomes;
- data-quality failures;
- weekend follow-up;
- reopen boundaries;
- transfer categories.

V2 model classification uses a separate approximately 50-ticket labelled set.

## 20. Reconciliation Invariants

For every cohort week:

```text
ai_first_count
= ai_end_to_end_count + ai_then_cs_count
```

```text
normally_classified_count
= ai_end_to_end_count + ai_then_cs_count + direct_cs_count
```

```text
total_tickets
= normally_classified_count + unclassified_count
```

```text
reopen_within_7d_numerator
<= reopen_within_7d_denominator
<= mature_ai_first_count
```

Additional requirements:

- no weekend-start ticket enters a cohort;
- every transfer category contributes once per dimension;
- every missing category is visible as `unknown`;
- rerunning an unchanged payload creates no duplicate score;
- a changed lifecycle updates the existing score;
- local manifest and Langfuse readback reconcile before dashboard creation.
- every Langfuse UI weekly bucket equals the score's business `cohort_week`.
- no `weekly_cs_reopen_7d_rate` or denominator score exists for an immature
  week; neither zero nor a sentinel value represents missing maturity.

## 21. Demo Definition

The first demo is ready when:

- the standalone project installs successfully;
- unit and client tests pass;
- a real read-only dry run completes against the target project;
- the dry-run quality gates are reported;
- the canary create/update/read/delete flow succeeds;
- structurally valid core score families are written and reconciled;
- category score families are written only when their own quality gate passes;
- the native dashboard exists in the target Langfuse project;
- the selected Layered scorecard core widgets render with real data;
- any category family blocked by quality gates is identified in the local
  summary and dashboard description rather than represented with misleading
  values;
- the dashboard URL and any material caveats are handed back to the user.
