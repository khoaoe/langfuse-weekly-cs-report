# CSAT Ticket-Grain Outcome, Skill/Category, and Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Freshdesk CSAT section decision-useful by counting each ticket once from its latest Admin CS ZaloPay survey response, letting the reader inspect that population by the existing Langfuse outcome, Skill, or Category one dimension at a time, replacing the misleading “bình luận” contract with source-faithful “nội dung phản hồi”, exposing that latest satisfaction category safely in Ticket Explorer, removing zero-ticket placeholder rows from the existing ticket-attribute comparison, and separately showing how often a Langfuse `AI xử lý trọn` ticket later receives a verified public reply from a human Freshdesk agent.

**Architecture:** Keep the existing GET-only, per-ticket Freshdesk survey fetch and private CSAT cache schema v2 unchanged. Derive one shared latest approved response map while projecting the dashboard from the cache plus `SessionMetrics`; use it for outcome/Skill/Category rollups, per-response sequence metadata, and a strict browser-safe `TicketRow.csat_satisfaction` state. Publish that shape atomically under storage/browser v11. In a later independent batch, add a metadata-only Freshdesk conversation job with a separate private reconciliation cache v1; it reads only author/direction/visibility/source/time in memory and persists only one derived `human_replied_after_ai` state per ticket. Its aggregate enters storage/browser v12 as `outcome_reconciliation`, without changing any Langfuse outcome. The React section uses the same `effectiveWeek` and cohort as the rest of BelowFold, defaults to grouping by outcome, and exposes one explicit `Nhóm theo` selector rather than placing three dimensions in one table. Breakdown rows are read-only; an explicit clearable selector inside the feedback panel applies the matching existing Ticket Explorer filter and filters the feedback list.

**Tech Stack:** Python 3.11, existing dataclasses/stdlib only, FastAPI projection, React 19, TypeScript 5.9 strict, Zod 4, Vitest/Testing Library, Playwright, CSS Modules.

## Global Constraints

- Authorities: `PRODUCT.md` Freshdesk privacy deviation, `docs/SPEC-v2.md` §6.1, and `docs/superpowers/specs/2026-08-01-freshdesk-csat-integration-design.md` remain binding.
- Scope is: (1) ticket-grain CSAT selectable by Langfuse outcome, Skill, or Category; (2) correct response grain and user-facing feedback wording; (3) show/filter the latest satisfaction category in Ticket Explorer; (4) hide rows whose ticket total is zero in `So sánh theo thuộc tính ticket`; and (5) separately reconcile Langfuse `AI xử lý trọn` tickets against a later verified human-agent reply in Freshdesk.
- “Admin CS ZaloPay” is the approved **AI CS Agent** account. Survey inclusion remains exactly `satisfaction_ratings[].agent_id in bot_agent_ids`; no human-CS survey is added.
- `ai_end_to_end`, `ai_then_cs`, `direct_cs`, and `unclassified` remain Langfuse-only definitions. This plan does not change `classification.py`, AI First, transfer, reopen, `gt4_turn`, TPE, segment, or the 14-column weekly report.
- Reconciliation is observational and never subtracts from or rewrites `ai_end_to_end`/AI First. The UI must state both the mismatch count and that the Langfuse KPI remains unchanged.
- Human identity is never inferred from conversation display text at runtime. The one-time private roster review starts from `ticket_fields.default_agent.choices`, excludes the approved `Admin CS ZaloPay` bot and non-person/service accounts, and materializes approved human/excluded IDs only. A requester with the same display name is still excluded because a valid human reply requires an approved agent ID plus `incoming == false`; names never enter cache, snapshot, API, DOM, CSV, or logs.
- A qualifying later human reply must be public outgoing (`incoming == false`, `private != true`, `source != 6`), authored by an approved human agent ID, and ordered after a public outgoing reply authored by the approved Admin CS ZaloPay bot ID. An unresolved author after the bot makes the ticket state `null`, never `false`; a known excluded service account does not count as human.
- `>4 lượt trả lời` is an independent ticket attribute. It must not be used to redefine `ai_end_to_end` or any other outcome.
- `Nhóm theo` has exactly three values: `Kết quả xử lý` (default), `Skill`, and `Category`. Render only one grouping at a time; do not add App, Product Code, Intent, TPE, or a cross-tab in this release.
- Skill and Category labels must reuse the same normalized values as the existing segment/Explorer contract. Skill must preserve `Nhiều skill` and `Chưa ghi nhận`; Category must preserve the existing missing label. Do not derive a new taxonomy from feedback text.
- Freshdesk contract evidence currently exposes one `feedback` string and `ratings.default_question`; observed `ratings.question_*` fields are null. Therefore the product term is **“nội dung phản hồi”**, not “bình luận”, “lựa chọn có sẵn”, or “free text”. Do not add a guessed `feedback_kind`, parser, regex taxonomy, or option tags.
- Headline and all outcome/Skill/Category percentages use **one latest response per ticket**. The detail explorer retains every redacted response. Latest ordering is `responded_at`, then private `response_key` as deterministic tie-breaker; `response_key` never enters browser payload.
- `TicketRow.csat_satisfaction` uses that same latest approved Admin CS ZaloPay response and has exactly five states: `positive`, `neutral`, `negative`, `unrated`, or `null`. `unrated` means the ticket's cohort week is in `cache.fetched_weeks` but no approved response exists; `null` means the week was not fetched (or the CSAT cache is unavailable). Never display `null` as “Chưa có đánh giá”.
- A ticket stays in the cohort week of its Langfuse `SessionMetrics.cohort_week`; never group it by survey `responded_at`.
- CSAT cache schema stays at `2`; `runtime/csat_cache.json` is not repurposed. Reconciliation uses a separate strict private cache v1 and a separate CLI command. The serving process still never calls Freshdesk.
- Dashboard storage/browser schema changes atomically from v10 to v11 in the CSAT backend-projection task, then from v11 to v12 in the reconciliation batch. Python exact-key validation and Zod strict validation must land together for each bump.
- Browser/API may expose Ticket ID, the already-visible normalized Skill/Category labels, the four-state safe `csat_satisfaction` token (`positive|neutral|negative|unrated`, nullable when unfetched), and already-approved redacted feedback only. It must not expose agent IDs/names, rating source IDs/hashes, user IDs, group IDs, raw `feedback`, conversation text, attachment metadata, prompt/response, `traceId`, or `sessionId`.
- Preserve signed redaction behavior: raw feedback exists in memory only, payload text is at most 200 characters, disclosure is closed by default, and pagination remains 10 entries per page.
- Do not add a dependency, route, Freshdesk request from the serving process, chart, LLM narrative, status card, response-rate metric, or automatic causal conclusion.
- Preserve the dirty worktree. Do not reset, stash, delete, overwrite unrelated changes, or commit without fresh explicit user authorization.
- Every implementation task is sequential TDD: focused RED → minimal implementation → focused GREEN → full gate. If a contract measurement below differs materially, stop and report before coding.

---

### Task 0: Re-verify the live contract and baseline before editing

**Files:**
- Read only: `src/weekly_cs_report/dashboard_schema.py`
- Read only: `src/weekly_cs_report/csat_cache.py`
- Read only: `artifacts/freshdesk_discovery/contract.json`
- Read only: `runtime/csat_cache.json`
- Read only: `runtime/dashboard_snapshot.json`

**Interfaces:**
- Confirms dashboard storage v10 and cache schema v2 before the v11 change.
- Confirms the cache has response-grain rows and may contain more than one response per Ticket ID.
- Produces aggregate terminal evidence only; no Ticket ID, feedback text, agent ID, or credential value may be printed.

- [ ] **Step 1: Record the protected dirty baseline and versions**

```bash
git branch --show-current
git status --short
rg -n '^_STORAGE_VERSION|^_CACHE_SCHEMA_VERSION' \
  src/weekly_cs_report/dashboard_schema.py \
  src/weekly_cs_report/csat_cache.py
stat -f "%Sp %N" runtime runtime/csat_cache.json runtime/dashboard_snapshot.json
```

Expected: branch and dirty paths are recorded without cleanup; current source versions are dashboard `10`, cache `2`; runtime is `drwx------` and both JSON files are `-rw-------`.

- [ ] **Step 2: Recompute only safe aggregate grain evidence**

```bash
jq '{
  cache_schema: .schema_version,
  response_count: (.responses | length),
  ticket_count: (.responses | map(.ticket_id) | unique | length),
  tickets_with_multiple_responses: (
    [.responses | group_by(.ticket_id)[] | select(length > 1)] | length
  ),
  observed_rating_tokens: (.responses | map(.rating_raw) | unique | sort)
}' runtime/csat_cache.json

jq '{
  dashboard_schema: .schema_version,
  csat_sources: [
    .dashboard.views.mon_fri.csat.source,
    .dashboard.views.mon_sun.csat.source
  ] | unique
}' runtime/dashboard_snapshot.json
```

Expected invariants: `response_count >= ticket_count`, at least one multi-response ticket exists, observed rating tokens are a subset of `[-103, 100, 103]`, and every non-null CSAT source is `freshdesk`. Counts are snapshot-specific and must not be copied into source constants.

- [ ] **Step 3: Reconfirm that feedback kind is not observable**

```bash
jq '{
  satisfaction_shape: .endpoints.satisfaction_ratings.shape,
  survey_observations: .survey_observations
}' artifacts/freshdesk_discovery/contract.json
```

Expected: the rating shape has a string `feedback`, numeric `ratings.default_question`, and observed `ratings.question_*` fields are null. If the live contract now exposes structured answer IDs/labels, **STOP** and revise this plan instead of discarding that stronger source contract.

- [ ] **Step 4: Run the unchanged baseline**

```bash
npm run test:unit
npm run typecheck
npm run build
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
git diff --check
```

Expected: all commands pass before the first RED test. Existing failures are reported as baseline failures; they are not silently absorbed into this feature.

---

### Task 1: Project and validate v11 atomically in Python and TypeScript

**Files:**
- Modify: `src/weekly_cs_report/dashboard_schema.py`
- Modify: `src/weekly_cs_report/web.py`
- Modify: `tests/test_dashboard_schema.py`
- Modify: `tests/test_dashboard_cache.py`
- Modify: `tests/test_web.py`
- Modify: `frontend/src/lib/dashboard-schema.ts`
- Modify: `frontend/test/dashboard-schema.test.ts`
- Modify: `frontend/test/fixtures/dashboard.ts`
- Modify: `frontend/test/fixtures/cohort.ts` only where copied CSAT fixtures require the new shape

**Interfaces:**
- Changes the private projection signature to `_csat_payload(sessions, weekly, cache, ordered_responses)`, where `ordered_responses` is the one immutable Ticket ID map computed in `project_dashboard`; this is internal-only and does not change a route.
- Adds `TicketRow.csat_satisfaction: Literal["positive", "neutral", "negative", "unrated"] | None` and the matching optional `csat_satisfaction` filter to `ticket_page` and `/api/tickets`.
- Produces per observed cohort week:

```python
{
    "response_count": int,       # every approved bot response
    "ticket_count": int,         # distinct tickets; denominator below
    "positive": int,             # latest response per ticket
    "neutral": int,              # latest response per ticket
    "negative": int,             # latest response per ticket
    "by_outcome": {
        "ai_end_to_end": {
            "ticket_count": int,
            "positive": int,
            "neutral": int,
            "negative": int,
        },
        "ai_then_cs": {
            "ticket_count": int,
            "positive": int,
            "neutral": int,
            "negative": int,
        },
        "direct_cs": {
            "ticket_count": int,
            "positive": int,
            "neutral": int,
            "negative": int,
        },
        "unclassified": {
            "ticket_count": int,
            "positive": int,
            "neutral": int,
            "negative": int,
        },
    },
    "by_dimension": {
        "skill": [
            {
                "value": str,
                "ticket_count": int,
                "positive": int,
                "neutral": int,
                "negative": int,
            }
        ],
        "issue_category": [
            {
                "value": str,
                "ticket_count": int,
                "positive": int,
                "neutral": int,
                "negative": int,
            }
        ],
    },
    "feedback_entries": [
        {
            "ticket_id": str,
            "responded_at": str,
            "satisfaction_bucket": str,
            "outcome": str,
            "skill": str,
            "issue_category": str,
            "text": str,
            "response_number": int,
            "response_total": int,
            "is_latest_for_ticket": bool,
        }
    ],
}
```

- `_STORAGE_VERSION` becomes `11` in this task.
- Cache schema remains `2`; `response_key` is consumed only as a private tie-breaker.

- [ ] **Step 1: Write RED projection tests for multiple responses and outcomes**

Extend `tests/test_dashboard_schema.py` with a fixture containing:

- Ticket `145665`, outcome `ai_end_to_end`, Skill `interbank-fund-transfer`, Category `Chuyển tiền`, older positive response and newer negative response.
- Ticket `145667`, outcome `direct_cs`, Skill `withdraw`, Category `Rút tiền`, one positive response.
- Ticket `145666`, outcome `ai_end_to_end`, multi-skill label `Nhiều skill`, missing Category label, and two equal-timestamp responses whose `response_key` values establish deterministic order: the older ordered response has redacted text and the later ordered response has `comment_redacted=None`. This proves the no-text latest response still controls the ticket rating while the visible historical entry remains `Lần 1/2`.

Create one reusable test helper named `_csat_v11_snapshot()` that returns the valid projected `DashboardSnapshot` from this fixture. All strict-validation tests below mutate `_csat_v11_snapshot().storage_dict()`; do not introduce a hand-built payload helper that can drift from projection.

Assert the exact contract rather than only individual fields:

```python
week = dashboard["views"]["mon_fri"]["csat"]["by_week"]["2026-07-20"]

assert week["response_count"] == 5
assert week["ticket_count"] == 3
assert week["ticket_count"] == (
    week["positive"] + week["neutral"] + week["negative"]
)
assert sum(row["ticket_count"] for row in week["by_outcome"].values()) == 3
assert week["by_outcome"]["ai_end_to_end"] == {
    "ticket_count": 2,
    "positive": 0,
    "neutral": 1,
    "negative": 1,
}
assert sum(row["ticket_count"] for row in week["by_dimension"]["skill"]) == 3
assert sum(
    row["ticket_count"] for row in week["by_dimension"]["issue_category"]
) == 3
assert next(
    row for row in week["by_dimension"]["skill"] if row["value"] == "Nhiều skill"
)["ticket_count"] == 1
assert [
    (
        item["ticket_id"],
        item["response_number"],
        item["response_total"],
        item["is_latest_for_ticket"],
        item["outcome"],
        item["skill"],
        item["issue_category"],
    )
    for item in week["feedback_entries"]
] == [
    ("145665", 1, 2, False, "ai_end_to_end", "interbank-fund-transfer", "Chuyển tiền"),
    ("145665", 2, 2, True, "ai_end_to_end", "interbank-fund-transfer", "Chuyển tiền"),
    ("145666", 1, 2, False, "ai_end_to_end", "Nhiều skill", "Không xác định"),
    ("145667", 1, 1, True, "direct_cs", "withdraw", "Rút tiền"),
]
```

Assert the same fixture's browser-safe ticket projection stores `skill == "Nhiều skill"` for `145666`. Through `ticket_page(...)` or the existing `/api/tickets` route test, filtering `skill=Nhiều skill` must return that ticket while `skill=Chưa ghi nhận` must not. This RED test lands before the shared Skill-bucket implementation; do not postpone it as a UI-only assertion.

Also assert the strict TicketRow satisfaction states:

- `145665` is `negative`, matching its latest approved response rather than its older positive response.
- `145666` is `neutral` even though its latest response has no visible feedback text.
- `145667` is `positive`.
- A ticket in a fetched cohort week with no approved Admin CS ZaloPay response is `unrated`.
- A ticket in an unfetched cohort week is `null`, not `unrated`.

Add `/api/tickets?csat_satisfaction=negative` and `...=unrated` tests, plus rejection of `csat_satisfaction=unknown`, duplicate query keys, and overlong values. Sorting tests must keep unrated and unfetched rows after rated rows in both directions; rated ascending order is `negative`, `neutral`, `positive`, and descending reverses only those three.

Also assert `mon_fri` excludes a weekend-start ticket while `mon_sun` includes it, and both views independently recompute latest response, outcome, Skill, and Category totals from their own session population.

- [ ] **Step 2: Write RED strict-validation and storage-version tests**

Update the expected storage version from `10` to `11`. Add parameterized invalid payload cases:

```python
@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda week: week.__setitem__("ticket_count", 999), "ticket count"),
        (lambda week: week["by_outcome"]["ai_end_to_end"].__setitem__("positive", 999), "outcome"),
        (lambda week: week["feedback_entries"][0].__setitem__("response_number", 0), "response number"),
        (lambda week: week["by_dimension"]["skill"][0].__setitem__("ticket_count", 999), "dimension"),
        (lambda week: week["feedback_entries"][0].__setitem__("agent_id", 42), "unsupported or missing fields"),
    ],
)
def test_csat_v11_rejects_nonreconciling_or_extra_fields(mutate, message):
    value = _csat_v11_snapshot().storage_dict()
    week = value["dashboard"]["views"]["mon_sun"]["csat"]["by_week"]["2026-07-20"]
    mutate(week)
    with pytest.raises(ValueError, match=message):
        DashboardSnapshot.from_storage_dict(value)
```

Add a test that an otherwise-valid v10 snapshot is rejected after the version bump. Update `tests/test_dashboard_cache.py` so refresh-success logging expects schema version `11` and no hardcoded `10` remains.

Separately mutate a stored ticket's `csat_satisfaction` to `"unknown"` and delete the field once; both must fail strict v11 loading. Add explicit extra-field rejection cases for `survey_id`, `rating_raw`, `comment_present`, and `response_key` on a feedback entry so private cache/source metadata cannot drift into the browser contract.

- [ ] **Step 3: Confirm focused RED**

```bash
uv run --isolated --extra dev --locked pytest -q \
  tests/test_dashboard_schema.py \
  tests/test_dashboard_cache.py \
  tests/test_web.py
```

Expected: failures show the old response-grain shape, old `comments` key, and storage version `10`.

- [ ] **Step 4: Implement deterministic latest-response projection**

In `dashboard_schema.py`, keep all raw cache rows and derive ordered rows per ticket:

```python
def _csat_response_order(response: CachedCSATResponse) -> tuple[datetime, str]:
    return (
        _parse_utc_iso(response.responded_at, "CSAT responded_at"),
        response.response_key,
    )


def _ordered_csat_by_ticket(
    responses: tuple[CachedCSATResponse, ...],
) -> dict[str, tuple[CachedCSATResponse, ...]]:
    grouped: dict[str, list[CachedCSATResponse]] = defaultdict(list)
    for response in responses:
        grouped[response.ticket_id].append(response)
    return {
        ticket_id: tuple(sorted(items, key=_csat_response_order))
        for ticket_id, items in sorted(grouped.items())
}
```

Compute `_ordered_csat_by_ticket(cache.responses)` once in `project_dashboard` and pass the immutable result into both ticket projection and `_csat_payload`; do not independently select “latest” in two paths. For each week, calculate top-level buckets only from `items[-1]` for every ticket. Calculate `by_outcome` using the matched `SessionMetrics.outcome`; do not infer outcome from the rating, response timestamp, or Freshdesk fields.

Extract one shared Skill-bucket helper from the existing `_segment_value(..., "skill", ...)` branch and reuse it in segments, CSAT, and `_ticket_row`. It must return the existing normalized labels: the single recorded skill name, `Nhiều skill`, or `Chưa ghi nhận`. This small projection fix is required so selecting a CSAT Skill filter and filtering Ticket Explorer identifies the same tickets; do not leave multi-skill tickets serialized as `None` and then interpreted as `Chưa ghi nhận`. Category uses the existing `_safe_dimension(session.dimensions.issue_category)` value.

Build `by_dimension.skill` and `by_dimension.issue_category` from each ticket's latest response only. Every dimension row has the same exact four count fields as an outcome row plus `value`; sort rows by descending `ticket_count`, then the existing natural label order. Generate `feedback_entries` from every response whose existing `comment_redacted` is non-null, assigning the matched ticket's normalized `skill` and `issue_category` plus sequence metadata from its position in the full ordered tuple.

Project `TicketRow.csat_satisfaction` from the same ordered map:

```python
if csat_cache is None or session.cohort_week.isoformat() not in csat_cache.fetched_weeks:
    csat_satisfaction = None
elif session.session_id not in ordered_csat_by_ticket:
    csat_satisfaction = "unrated"
else:
    csat_satisfaction = ordered_csat_by_ticket[session.session_id][-1].satisfaction_bucket
```

Only the three cache-validated satisfaction buckets may enter the last branch. Add `csat_satisfaction` to `_TICKET_KEYS`, strict ticket validation, `/api/tickets` query allowlisting, and filtering. Special-case its sort so rated rows use the semantic order `negative < neutral < positive`, while `unrated` then `null` remain after all rated rows for both directions. No agent/source ID accompanies the field.

Sort feedback entries deterministically by `(responded_at datetime, ticket_id, response_number)` before serialization. Never include `response_key` in the returned mapping.

- [ ] **Step 5: Implement exact v11 validation and bump the version**

Set:

```python
_STORAGE_VERSION = 11
```

Replace the old CSAT validation equations with:

```python
assert response_count >= ticket_count
assert ticket_count == positive + neutral + negative
assert sum(row["ticket_count"] for row in by_outcome.values()) == ticket_count
assert sum(row["positive"] for row in by_outcome.values()) == positive
assert sum(row["neutral"] for row in by_outcome.values()) == neutral
assert sum(row["negative"] for row in by_outcome.values()) == negative
for rows in by_dimension.values():
    assert sum(row["ticket_count"] for row in rows) == ticket_count
    assert sum(row["positive"] for row in rows) == positive
    assert sum(row["neutral"] for row in rows) == neutral
    assert sum(row["negative"] for row in rows) == negative
```

Validate `by_dimension` with exactly `skill` and `issue_category`; validate every dimension row with exactly `value`, `ticket_count`, `positive`, `neutral`, and `negative`. Reject duplicate or unsafe `value` labels and require each dimension to reconcile independently to the top-level ticket and satisfaction counts. Validate each outcome object with exact keys and each feedback entry with the ten exact keys above. Require:

- `outcome` is one of the four existing outcomes.
- `1 <= response_number <= response_total`.
- `is_latest_for_ticket == (response_number == response_total)`.
- For repeated visible entries of one Ticket ID, `response_total`, `outcome`, `skill`, and `issue_category` are stable and visible `response_number` values are unique.
- `len(feedback_entries) <= response_count`.
- Existing safe Ticket ID, UTC timestamp, 200-character limit, URL/PII safety, and safe-string checks still run.

Do not require one visible entry per response: a response without feedback is valid and may cause visible sequence numbers to skip.

- [ ] **Step 6: Run focused backend GREEN without creating a version checkpoint**

```bash
uv run --isolated --extra dev --locked pytest -q \
  tests/test_dashboard_schema.py \
  tests/test_dashboard_cache.py \
  tests/test_csat_cache.py \
  tests/test_freshdesk_csat.py \
  tests/test_web.py
```

Expected: focused backend tests pass. `tests/test_csat_cache.py` still proves two responses per ticket remain in private cache schema v2. **Do not checkpoint, commit, hand off, or run the full suite yet:** storage v11 is not an atomic deliverable until the TypeScript contract in Part B below is GREEN.

#### Part B of Task 1: Make the TypeScript contract exactly match v11

**Interfaces:**
- Reuses exported `OutcomeSchema` and `Outcome`.
- Replaces `CsatCommentSchema`/`CsatComment` with `CsatFeedbackEntrySchema`/`CsatFeedbackEntry`.
- Replaces `ticket_count_with_response` with `ticket_count` and `comments` with `feedback_entries`.
- Adds `by_outcome: Record<Outcome, CsatOutcomeCounts>` with all four outcome keys required.
- Adds strict `by_dimension.skill` and `by_dimension.issue_category` arrays of `CsatDimensionCounts`; no other dimension key is accepted.
- Adds required nullable `TicketRow.csat_satisfaction` with only `positive|neutral|negative|unrated|null` accepted.

- [ ] **Step B1: Write RED Zod parity tests**

Define a valid v11 fixture and assert successful parsing. Add strict rejection cases for:

```ts
const feedbackEntry = {
  ticket_id: "6991254",
  responded_at: "2026-07-21T01:00:00Z",
  satisfaction_bucket: "positive" as const,
  outcome: "ai_end_to_end" as const,
  skill: "interbank-fund-transfer",
  issue_category: "Chuyển tiền",
  text: "Cảm ơn, xử lý nhanh",
  response_number: 1,
  response_total: 2,
  is_latest_for_ticket: false,
};

const csatWeek = {
  response_count: 2,
  ticket_count: 1,
  positive: 0,
  neutral: 1,
  negative: 0,
  by_outcome: {
    ai_end_to_end: { ticket_count: 1, positive: 0, neutral: 1, negative: 0 },
    ai_then_cs: { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
    direct_cs: { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
    unclassified: { ticket_count: 0, positive: 0, neutral: 0, negative: 0 },
  },
  by_dimension: {
    skill: [
      { value: "interbank-fund-transfer", ticket_count: 1, positive: 0, neutral: 1, negative: 0 },
    ],
    issue_category: [
      { value: "Chuyển tiền", ticket_count: 1, positive: 0, neutral: 1, negative: 0 },
    ],
  },
  feedback_entries: [feedbackEntry],
};
```

Reject old `comments`, old `ticket_count_with_response`, missing outcome keys, an outcome bucket that does not reconcile, a missing/extra dimension, duplicate dimension values, a dimension total that does not reconcile, `response_number=0`, `response_number>response_total`, a mismatched latest flag, extra private fields (`agent_id`, `survey_id`, `rating_raw`, `comment_present`, `response_key`), an unsafe/over-200-character `text`, and a TicketRow whose `csat_satisfaction` is missing or invalid.

- [ ] **Step B2: Confirm RED**

```bash
npx vitest run frontend/test/dashboard-schema.test.ts
```

Expected: failures because the frontend still requires the v10 comment shape.

- [ ] **Step B3: Implement strict schemas and refinements**

Add:

```ts
const CsatOutcomeCountsSchema = z
  .object({
    ticket_count: nonNegativeInteger,
    positive: nonNegativeInteger,
    neutral: nonNegativeInteger,
    negative: nonNegativeInteger,
  })
  .strict()
  .refine(
    (value) =>
      value.ticket_count === value.positive + value.neutral + value.negative,
    { message: "CSAT outcome buckets must reconcile." },
  );

const CsatDimensionCountsSchema = z
  .object({
    value: safeLabel,
    ticket_count: nonNegativeInteger,
    positive: nonNegativeInteger,
    neutral: nonNegativeInteger,
    negative: nonNegativeInteger,
  })
  .strict()
  .refine(
    (value) =>
      value.ticket_count === value.positive + value.neutral + value.negative,
    { message: "CSAT dimension buckets must reconcile." },
  );

export const CsatFeedbackEntrySchema = z
  .object({
    ticket_id: TicketIdSchema,
    responded_at: UtcDateTimeSchema,
    satisfaction_bucket: z.enum(["positive", "neutral", "negative"]),
    outcome: OutcomeSchema,
    skill: safeLabel,
    issue_category: safeLabel,
    text: z.string().min(1).max(200),
    response_number: z.number().int().positive(),
    response_total: z.number().int().positive(),
    is_latest_for_ticket: z.boolean(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.response_number > value.response_total) {
      context.addIssue({ code: "custom", path: ["response_number"], message: "CSAT response number exceeds total." });
    }
    if (value.is_latest_for_ticket !== (value.response_number === value.response_total)) {
      context.addIssue({ code: "custom", path: ["is_latest_for_ticket"], message: "CSAT latest marker is inconsistent." });
    }
  });
```

Add an exact outer object `{ skill: z.array(CsatDimensionCountsSchema), issue_category: z.array(CsatDimensionCountsSchema) }`. Make `CsatWeekSchema.superRefine` enforce the same top-level/outcome/dimension equations as Python, including uniqueness of `value` inside each dimension. Keep the record strict and all four outcomes required; no optional outcome row or dimension.

Add this required field to `TicketRowSchema` in the same atomic change:

```ts
csat_satisfaction: z
  .enum(["positive", "neutral", "negative", "unrated"])
  .nullable(),
```

- [ ] **Step B4: Update shared fixtures without weakening strictness**

Every fixture with `csat !== null` must use the v11 shape. Keep `csat: null` fixtures unchanged. Do not add `.passthrough()`, optional old keys, a union accepting v10, or test-only schema relaxation.

Every TicketRow fixture must include `csat_satisfaction`; use `null` only where the fixture intentionally represents an unfetched/unavailable Freshdesk scope, and `unrated` where the week is fetched but no approved survey exists. Do not make the new field optional to preserve v10 compatibility.

- [ ] **Step B5: Run the atomic v11 GREEN gate**

```bash
npx vitest run frontend/test/dashboard-schema.test.ts
npm run test:unit
npm run typecheck
npm run build
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
git diff --check
```

Expected: the complete frontend and Python gates pass with no `any`, `@ts-ignore`, old comment-shape compatibility branch, or interval in which a checked-in v11 backend accepts a v10 frontend. Task 1 is now one independently reviewable schema-version change.

---

### Task 2: Render the selectable outcome/Skill/Category table and source-faithful feedback explorer

**Files:**
- Create: `frontend/src/components/CsatBreakdownTable.tsx`
- Modify: `frontend/src/components/CsatSection.tsx`
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/src/components/DashboardScreen.tsx`
- Modify: `frontend/src/components/csat-section.module.css`
- Modify: `frontend/test/report-sections.test.tsx`
- Modify: `frontend/test/dashboard-screen.test.tsx`

**Interfaces:**
- Add `type CsatGrouping = "outcome" | "skill" | "issue_category"` beside the CSAT component. This is a UI analysis choice, not a new Ticket Explorer filter key.
- `CsatSectionProps` adds:

```ts
readonly activeBreakdownFilters: Pick<
  TicketFilters,
  "outcome" | "skill" | "issue_category"
>;
readonly onBreakdownSelect: (
  grouping: CsatGrouping,
  value: string,
) => void;
readonly onBreakdownGroupingChange: () => void;
```

- `BelowFoldProps` passes these values through unchanged.
- `DashboardScreen` owns the existing `filters.outcome`, `filters.skill`, and `filters.issue_category`. The feedback selector uses the matching existing filter; no new filter key is created.
- Switching `Nhóm theo` clears only those three CSAT analysis filters so a hidden prior selection cannot silently narrow the feedback list. It preserves week and every unrelated Explorer filter.
- Selecting a value in `Lọc nội dung theo …` starts a CSAT drill-down: it preserves the selected cohort week, clears every other Ticket Explorer filter, and sets only the matching outcome/Skill/Category value. Choosing `Tất cả` passes an empty value and restores the unfiltered feedback/Ticket Explorer population. This prevents an old App/Product/Intent/TPE/satisfaction filter from silently making Ticket Explorer narrower than the visible CSAT grouping.
- `CsatBreakdownTable` consumes one scoped `CsatWeek` and never fetches data.

- [ ] **Step 1: Write RED tests for ticket-grain grouping**

In `frontend/test/report-sections.test.tsx`, use a v11 week where `response_count=23`, `ticket_count=20`, and outcome rows reconcile. Assert:

- The selector `Nhóm theo` has exactly `Kết quả xử lý`, `Skill`, and `Category`; `Kết quả xử lý` is selected by default.
- Default column headers are `Kết quả xử lý`, `Ticket có đánh giá`, `Rất hài lòng`, `Bình thường`, `Rất tệ`.
- The total row shows `20 ticket` and a subordinate `23 phản hồi` because responses exceed tickets.
- Rating cells use `số · tỷ lệ` over 20 tickets.
- An outcome with 18 tickets shows counts only and the visible label `Mẫu nhỏ`; it does not show percentages.
- A zero-ticket outcome row is omitted.
- Selecting `Skill` replaces, rather than appends to, the outcome rows; the first header becomes `Skill`, and the rows come from `by_dimension.skill`.
- Selecting `Category` likewise shows only `by_dimension.issue_category` and changes the first header to `Category`.
- A dimension with more than 10 non-zero values shows 10 by default plus `Xem tất cả N nhóm`; expanding reveals all rows and `Thu gọn` restores 10. Outcome always shows its at-most-four rows without this control.
- There is no `CS agent` one-row table and no user-facing `ticket_count_with_response` wording.

Example assertions:

```ts
expect(within(totalRow).getByText("20 ticket")).toBeVisible();
expect(within(totalRow).getByText("23 phản hồi")).toBeVisible();
expect(within(totalRow).getByText("12 · 60,0%")).toBeVisible();
expect(within(smallRow).getByText("Mẫu nhỏ")).toBeVisible();
expect(within(smallRow).queryByText("%", { exact: false })).toBeNull();
```

- [ ] **Step 2: Write RED interaction tests for shared breakdown filtering**

In `frontend/test/dashboard-screen.test.tsx`, render a snapshot with feedback entries from two outcomes. Open the feedback panel, assert `AI xử lý trọn` is not a button, then select it from `Lọc nội dung theo Kết quả xử lý` and assert:

```ts
expect(outcomeFilter).toHaveValue("ai_end_to_end");
expect(screen.getByRole("region", { name: "Bộ lọc đang áp dụng" })).toHaveTextContent(
  "Kết quả: AI xử lý trọn",
);
expect(within(csatSection).getByText("Phản hồi outcome A")).toBeVisible();
expect(within(csatSection).queryByText("Phản hồi outcome B")).toBeNull();
const ticketExplorer = screen.getByRole("region", { name: "Ticket Explorer" });
expect(within(ticketExplorer).getByRole("combobox", { name: "Kết quả" })).toHaveValue(
  "ai_end_to_end",
);
```

Select `Tất cả` and assert the selector value, global outcome filter, and Ticket Explorer outcome are empty and both feedback entries return. Then:

1. Select `Skill`; assert the outcome selection and chip are cleared without changing the selected cohort week.
2. Select `interbank-fund-transfer` from `Lọc nội dung theo Skill`; assert the global chip says `Skill: interbank-fund-transfer`, Ticket Explorer receives that existing filter, and only matching feedback remains.
3. Select `Category`; assert the Skill selection clears, then select `Chuyển tiền` from `Lọc nội dung theo Category` and verify the same three-surface synchronization through `issue_category`.
4. Switch back to `Skill`, select `Nhiều skill`, and assert Ticket Explorer returns the multi-skill ticket, not the `Chưa ghi nhận` ticket. This is the regression test for the shared normalized Skill bucket.

Add one case that starts with `app`, `intent`, and `csat_satisfaction` filters active. Selecting a feedback grouping value must clear those three, preserve `cohort_week`, and leave exactly the selected grouping filter. This is deliberate drill-down behavior, not a merge with a hidden intersection.

Keep the viewport at the CSAT section; do not auto-scroll away when changing the selector.

- [ ] **Step 3: Write RED wording, sequence, pagination, and accessibility tests**

Replace every old “bình luận” expectation with exact source-faithful copy:

- `Xem 117 nội dung phản hồi` / `Ẩn 117 nội dung phản hồi`.
- `Phân trang nội dung phản hồi CSAT`.
- `Hiển thị 1–10 / 117 nội dung phản hồi`.
- `Không có nội dung phản hồi phù hợp.`

For a ticket with two responses, assert the first item shows `Lần 1/2`, the second shows `Lần 2/2 · Mới nhất`. A single-response ticket omits `Lần 1/1` to reduce noise. Assert the section contains no word `bình luận`, `free text`, or `lựa chọn có sẵn`.

Retain existing tests for:

- Closed disclosure by default.
- Week/rating/time filters run before pagination.
- Changing week, satisfaction, time sort, grouping, or the selected grouping row returns to page 1.
- 10 entries per page, bounded desktop page buttons, compact mobile page label, stable `#csat-comments`, `aria-live`, and focus retention.
- Freshdesk Ticket ID link, satisfaction color, and response timestamp.

- [ ] **Step 4: Confirm focused RED**

```bash
npx vitest run \
  frontend/test/report-sections.test.tsx \
  frontend/test/dashboard-screen.test.tsx
```

Expected: failures show the old one-row response-grain table, absent grouping selector, old comment copy, absent sequence metadata, and absent row interaction.

- [ ] **Step 5: Implement `CsatBreakdownTable`**

Use the existing `Outcome` type and `OUTCOME_FILTER_LABELS`; do not duplicate labels. Render an explicit native select above the table:

```tsx
<label>
  Nhóm theo
  <select value={grouping} onChange={handleGroupingChange}>
    <option value="outcome">Kết quả xử lý</option>
    <option value="skill">Skill</option>
    <option value="issue_category">Category</option>
  </select>
</label>
```

The default is `outcome`. Render the static total row first. For outcome, render non-zero rows in canonical order:

```ts
const OUTCOME_ORDER: readonly Outcome[] = [
  "ai_end_to_end",
  "ai_then_cs",
  "direct_cs",
  "unclassified",
];
```

For Skill and Category, consume the corresponding backend list, omit zero rows, and preserve its descending-volume order. Show at most 10 rows initially. The `Xem tất cả N nhóm`/`Thu gọn` button must be outside the table, have `aria-controls` pointing to the table, and reset to collapsed when week or grouping changes. The clearable feedback selector lists every non-zero value even when the read-only table is collapsed.

The total row's denominator is `data.ticket_count`. Each grouping row's denominator is its own `ticket_count`. Percentages are shown only when that row has at least 20 tickets. The first cell is a plain row header, not an action. Filtering lives beside the existing week/satisfaction/time controls:

```tsx
<label>
  Lọc nội dung theo {groupingLabel}
  <select value={activeValue} onChange={handleFilterChange}>
    <option value="">Tất cả</option>
    {options.map((option) => (
      <option value={option.value}>{option.label}</option>
    ))}
  </select>
</label>
```

Skill and Category options use their `value` verbatim after schema validation. The table must not claim causality or add narrative conclusions. Its caption is one concrete sentence: `Mỗi ticket được tính một lần theo đánh giá mới nhất.`

- [ ] **Step 6: Aggregate whole-period v11 data and convert the disclosure to a feedback explorer**

Update `aggregateWeeks()` so “Xem toàn kỳ” remains ticket-grain and every outcome reconciles. A ticket belongs to exactly one Langfuse cohort week, so these per-week ticket counts are additive:

```ts
function addOutcomeCounts(
  left: CsatWeek["by_outcome"][Outcome],
  right: CsatWeek["by_outcome"][Outcome],
): CsatWeek["by_outcome"][Outcome] {
  return {
    ticket_count: left.ticket_count + right.ticket_count,
    positive: left.positive + right.positive,
    neutral: left.neutral + right.neutral,
    negative: left.negative + right.negative,
  };
}
```

The whole-period result sums `response_count`, `ticket_count`, all three top-level buckets, each of the four `by_outcome` objects, and each Skill/Category row keyed by `value`, then concatenates `feedback_entries` only to satisfy the scoped `CsatWeek` aggregate contract. Re-sort merged dimension rows by descending ticket count then natural label. Add a test proving whole-period totals differ from the selected week while outcome, Skill, and Category all still reconcile; do not fall back to a view-level Freshdesk aggregate with another denominator.

Then rename component/type/local symbols from `Comment*` to `Feedback*` where they represent the user-facing concept. Use `feedback_entries`, not a compatibility alias to `comments`.

The feedback explorer must **not** derive its list from the aggregated `CsatWeek.feedback_entries`, because those entries intentionally contain no `cohort_week`. Preserve the current source-aware flattening pattern:

```ts
type FeedbackWithWeek = CsatFeedbackEntry & { readonly cohortWeek: string };

const feedback = Object.entries(csat.by_week).flatMap(([cohortWeek, week]) =>
  effectiveWeek === "" || cohortWeek === effectiveWeek
    ? week.feedback_entries.map((entry) => ({ ...entry, cohortWeek }))
    : [],
);
```

`cohortWeek` is client-local metadata and never enters the v11 browser payload. Add a regression test for `Xem toàn kỳ`: selecting one week in the feedback control must exclude an otherwise matching entry from another cohort week.

Filter in this order before paging:

```ts
entries
  .filter((entry) => weekMatches(entry))
  .filter((entry) => satisfactionMatches(entry))
  .filter((entry) => activeValue === "" || entry[grouping] === activeValue)
  .sort(timeOrder)
```

Reset page to 1 when the grouping or its active value changes externally:

```ts
useEffect(() => {
  setPage(1);
}, [grouping, activeValue]);
```

Keep all redacted historical responses visible. Add sequence wording only when `response_total > 1`; add `Mới nhất` only when `is_latest_for_ticket` is true. Do not infer whether text was typed or selected.

- [ ] **Step 7: Wire the three existing global filters without hidden intersections**

Add props through `BelowFold`. In `DashboardScreen`, pass the three current values and implement immutable callbacks equivalent to:

```tsx
activeBreakdownFilters={{
  outcome: filters.outcome,
  skill: filters.skill,
  issue_category: filters.issue_category,
}}
onBreakdownGroupingChange={() => {
  setFilters((current) => updateTicketFilters(current, {
    outcome: "",
    skill: "",
    issue_category: "",
  }));
}}
onBreakdownSelect={(grouping, value) => {
  setFilters((current) => ({
    ...EMPTY_TICKET_FILTERS,
    cohort_week: current.cohort_week,
    [grouping]: value,
  }));
}}
```

The component clears via the selector's `""` option. Switching `Nhóm theo` clears only the three breakdown filters; selecting a non-empty value intentionally resets every Explorer filter except cohort week so the downstream ticket population matches the feedback selection. Do not call `scrollToSection` for this interaction.

- [ ] **Step 8: Implement restrained responsive styling**

Reuse the existing table scroller, sticky first column, satisfaction semantic colors, focus-visible tokens, and 44×44 tap targets. Add only selectors needed for the grouping/filter controls, total-row support text, sample-size label, expand/collapse control, and response sequence. At 390 px both selects remain fully visible above the horizontally scrollable table. No new card mosaic, chart, gradient, hover-only information, or color-only state.

- [ ] **Step 9: Run focused GREEN and the frontend gate**

```bash
npx vitest run \
  frontend/test/report-sections.test.tsx \
  frontend/test/dashboard-screen.test.tsx \
  frontend/test/dashboard-schema.test.ts
npm run test:unit
npm run typecheck
npm run build
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
git diff --check
```

Expected: all frontend and Python gates pass; build budgets remain JS ≤250 KB gzip and CSS ≤80 KB gzip.

---

### Task 3: Add the latest satisfaction category to Ticket Explorer

**Files:**
- Create: `frontend/src/lib/csat-labels.ts`
- Create: `frontend/src/components/SatisfactionBadge.tsx`
- Create: `frontend/src/components/satisfaction-badge.module.css`
- Modify: `frontend/src/components/CsatSection.tsx`
- Modify: `frontend/src/components/TicketExplorer.tsx`
- Modify: `frontend/src/lib/dashboard-filters.ts`
- Modify: `frontend/src/lib/ticket-columns.ts`
- Modify: `frontend/test/report-sections.test.tsx`
- Modify: `frontend/test/ticket-columns.test.ts`
- Modify: `frontend/test/data-table-sorting.test.tsx`
- Modify copied TicketRow fixtures in other frontend tests only as required by the strict v11 field

**Interfaces:**
- Reuses `TicketRow.csat_satisfaction` and `/api/tickets?csat_satisfaction=` from Task 1.
- The displayed source is always the latest approved **Admin CS ZaloPay** response; human-CS surveys never enter the cache or this column.
- User-facing labels are exactly `Rất hài lòng`, `Bình thường`, `Rất tệ`, `Chưa có đánh giá`, and `—` for unfetched/unavailable scope.

- [ ] **Step 1: Write RED rendering, filtering, export, and migration tests**

In `frontend/test/report-sections.test.tsx`, render five TicketRows covering `positive`, `neutral`, `negative`, `unrated`, and `null`. Assert:

- A default-visible column named `Mức độ hài lòng (CS Agent)` appears immediately after `Kết quả`.
- Rated rows show `Rất hài lòng`, `Bình thường`, and `Rất tệ` with their shared semantic badge classes and readable text; color is never the sole signal.
- `unrated` shows `Chưa có đánh giá` in a neutral style.
- `null` shows `—`, not `Chưa có đánh giá`.
- The filter `Mức độ hài lòng (CS Agent)` offers `Tất cả`, the three Freshdesk labels, and `Chưa có đánh giá`; it does not offer an analysis option for unfetched `null` rows.
- Selecting `Rất tệ` sends `csat_satisfaction=negative`, resets pagination, and creates the chip `Mức độ hài lòng (CS Agent): Rất tệ`.
- CSV export writes user-facing labels, never `positive|neutral|negative|unrated` tokens.

In `frontend/test/data-table-sorting.test.tsx`, assert the `Mức độ hài lòng (CS Agent)` sort control requests `sort_by=csat_satisfaction`; backend tests from Task 1 own the semantic row order.

In `frontend/test/ticket-columns.test.ts`, cover a one-time column preference migration:

1. Change the current key to `weekly-cs-ticket-columns-v2` and keep the v1 key as a read-only legacy constant.
2. If v2 is absent and a valid v1 selection exists, preserve its order and insert `csat_satisfaction` immediately after `outcome`; if hidden, after `cohort_week`; if both were hidden, after mandatory `ticket_id`. Then persist v2.
3. If v2 exists, run the existing allowlist, duplicate removal, and mandatory Ticket-first normalization before respecting it; a valid normalized v2 may omit `csat_satisfaction` so a user can later hide the new column.
4. A tampered/invalid v1 or v2 value falls back to the safe v2 default; never copy unknown keys. Add separate tampered-v1 and tampered-v2 tests containing `raw_payload` and `trace_id`.
5. Do not delete or overwrite the v1 key.

- [ ] **Step 2: Confirm focused RED**

```bash
npx vitest run \
  frontend/test/report-sections.test.tsx \
  frontend/test/ticket-columns.test.ts \
  frontend/test/data-table-sorting.test.tsx
```

Expected: failures show the missing strict TicketRow field in old fixtures, missing column/filter, raw absence of labels, and no v1→v2 preference migration.

- [ ] **Step 3: Share one satisfaction wording/color component**

Move the existing three observed labels out of `CsatSection` into `csat-labels.ts`, add `unrated: "Chưa có đánh giá"`, and expose a total function that returns `"—"` for `null`. `SatisfactionBadge` renders the three rating labels with green/yellow/red styling and `unrated` with a neutral style. Refactor the CSAT feedback explorer to use the same badge; do not duplicate label maps or color rules between sections.

In `TicketExplorer.cellText`, return the same labels so table text and CSV export cannot diverge. The `null` state remains plain `—`; it is not wrapped in a colored badge.

- [ ] **Step 4: Add the default column and safe filter**

Add `{ key: "csat_satisfaction", label: "Mức độ hài lòng (CS Agent)", core: true }` immediately after outcome in `TICKET_COLUMNS`. Implement the v1→v2 preference migration exactly as tested.

Add `csat_satisfaction` to `TicketFilters`, `EMPTY_TICKET_FILTERS`, chip order/labels, display-token mapping, Ticket Explorer query, and the visible filter placed next to `Kết quả`. The four submitted values are `positive`, `neutral`, `negative`, and `unrated`; empty means all. Do not submit `null`, agent name, or survey ID.

Render `SatisfactionBadge` in the cell rather than falling through generic `cellText`. Keep the sortable header because the backend owns its explicit semantic ordering. Keep the field in the allowlisted column chooser/export path; do not expose any additional Freshdesk field.

- [ ] **Step 5: Run focused GREEN and the full frontend gate**

```bash
npx vitest run \
  frontend/test/report-sections.test.tsx \
  frontend/test/ticket-columns.test.ts \
  frontend/test/data-table-sorting.test.tsx \
  frontend/test/dashboard-schema.test.ts
npm run test:unit
npm run typecheck
npm run build
git diff --check
```

Expected: all pass; the new core column is visible for both new and safely migrated users, and no internal satisfaction token appears in rendered text or CSV.

---

### Task 4: Hide zero-ticket rows in the ticket-attribute comparison

**Files:**
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/test/report-sections.test.tsx`

**Interfaces:**
- No payload, storage version, filter, or sort-contract change.
- A segment row is data-bearing only when `counts.total > 0`.
- Zero in `ai_first`, `transferred`, or `reopen` does **not** hide a row whose `total` is positive.

- [ ] **Step 1: Write focused RED tests**

In `frontend/test/report-sections.test.tsx`, start with one active-week fixture with these Skill buckets:

```ts
{
  "interbank-fund-transfer": {
    total: 6,
    ai_first: 0,
    transferred: 0,
    reopen: 0,
  },
  "Chưa ghi nhận": {
    total: 0,
    ai_first: 0,
    transferred: 0,
    reopen: 0,
  },
}
```

Select the `Skill` tab and assert:

- `interbank-fund-transfer` remains visible despite all three child metrics being zero.
- No row button or row header named `Chưa ghi nhận` exists.
- The visible ticket cell remains `6 · 100%`; filtering placeholders must not alter the denominator.

Add a second case where every bucket in the selected dimension has `total=0`. Assert there is no data table row and the tab panel shows the concise empty state `Không có ticket trong phạm vi đang chọn.`. The empty state is not a fake table row and is not selectable.

Then parameterize the positive/zero pair over all five tabs — Category, App, Product Code, Skill, and Intent — so the test proves this is a shared row rule rather than a Skill-only exception. For every tab, the positive-total row has zero AI First/Chuyển CS/Reopen child values and must remain visible; the zero-total row must be absent.

- [ ] **Step 2: Confirm focused RED**

```bash
npx vitest run frontend/test/report-sections.test.tsx
```

Expected: the current component still renders `Chưa ghi nhận 0 · 0% · 0 · — · 0 · — · 0 · —` and fails the new assertions.

- [ ] **Step 3: Filter before deterministic sorting**

In `SegmentTable`, keep the existing all-bucket `total` calculation, then build rows with:

```ts
const source = Object.entries(buckets)
  .filter(([, counts]) => counts.total > 0)
  .map(([label, counts]) => ({ label, counts }));
```

Apply the existing deterministic and selected-column sorts after filtering. When `rows.length === 0`, keep the active tab panel and render the empty-state paragraph instead of an empty table. Do not mutate `segments`, delete mandatory zero buckets from the backend, weaken validation, or special-case only `Chưa ghi nhận`; the display rule applies to every dimension and label.

- [ ] **Step 4: Run focused GREEN and regression gates**

```bash
npx vitest run frontend/test/report-sections.test.tsx
npm run test:unit
npm run typecheck
npm run build
git diff --check
```

Expected: zero-total placeholders disappear across Category, App, Product Code, Skill, and Intent; positive-total rows remain sortable and clickable; no dashboard schema/version changes.

---

### Task 5: Reconcile `AI xử lý trọn` with later verified human-agent replies

**Files:**
- Create: `src/weekly_cs_report/outcome_reconciliation.py`
- Create: `src/weekly_cs_report/reconciliation_cache.py`
- Create: `tests/test_outcome_reconciliation.py`
- Create locally, never commit: `config/freshdesk_reconciliation_agents.v1.json`
- Modify privately, never commit: `artifacts/freshdesk_discovery/human_agent_candidates.v1.json`
- Modify: `src/weekly_cs_report/freshdesk_csat.py`
- Modify: `src/weekly_cs_report/cli.py`
- Modify: `src/weekly_cs_report/dashboard_schema.py`
- Modify: `src/weekly_cs_report/web.py`
- Modify: `tests/test_freshdesk_csat.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_dashboard_schema.py`
- Modify: `tests/test_dashboard_cache.py`
- Modify: `tests/test_web.py`
- Modify: `frontend/src/lib/dashboard-schema.ts`
- Modify: `frontend/src/components/CsatSection.tsx`
- Modify: `frontend/test/dashboard-schema.test.ts`
- Modify: `frontend/test/report-sections.test.tsx`

**Interfaces:**
- Adds a separate private config with exact keys `schema_version`, `approved_by`, `approved_at`, `bot_agent_ids`, `human_agent_ids`, `excluded_agent_ids`, and `source_hash`. IDs are positive, pairwise disjoint, and the config is a regular owner-only `0600` file.
- Adds a separate private cache v1 at `runtime/outcome_reconciliation_cache.json`; it persists only `ticket_id`, `cohort_week`, and `human_replied_after_ai: bool | null`, plus week-level fetch checkpoints. It never stores author/message IDs, names, message timestamps, body, body_text, attachments, or quoted text.
- Adds CLI `reconcile-freshdesk-outcomes`; the serving process only loads the derived cache and never calls Freshdesk.
- Changes dashboard storage/browser v11 → v12 atomically and adds `outcome_reconciliation` as a sibling of `csat` in each view:

```python
{
    "source": "freshdesk",
    "fetched_at": str,
    "by_week": {
        "2026-07-20": {
            "langfuse_ai_end_to_end": int,
            "checked_ticket_count": int,
            "human_replied_after_ai": int,
            "unresolved_ticket_count": int,
            "mismatch_rate": float | None,
        }
    },
}
```

- `langfuse_ai_end_to_end` trong khối đối chiếu là tập con có Ticket ID Freshdesk
  hợp lệ mà job được phép fetch; nó không thay đổi tổng outcome Langfuse và luôn
  `<= weekly.ai_end_to_end_count`. `mismatch_rate = human_replied_after_ai /
  checked_ticket_count`; unresolved tickets are excluded from the rate and shown
  separately. `checked + unresolved` may be lower than
  `langfuse_ai_end_to_end` when the cache is incomplete, and the UI must show
  that coverage instead of implying every ticket was checked.

- [ ] **Step 1: Materialize the PO identity decision privately**

Treat the user's 2026-08-03 instruction as approval of this decision procedure:

1. Candidate identity must originate from `ticket_fields.default_agent.choices`; requester names are never candidates.
2. Exclude the approved `Admin CS ZaloPay` bot ID before review.
3. Mark a candidate `human` only when its display name denotes a natural person; obvious team, call-center, QA, automation, test, or service-account labels are `exclude`.
4. Set every candidate decision, `approved_by="PO"`, `approved_at="2026-08-03"`, and `status="approved"`; no `unreviewed` row may remain.
5. Generate the runtime config with IDs only, a SHA-256 of the approved candidate artifact, and mode `0600`. Names remain only in the gitignored review artifact.

If a later discovery contains an unknown ID, do not auto-classify it: the ticket result becomes unresolved until the private roster is reviewed again.

- [ ] **Step 2: Write RED identity/config and author-sequence tests**

In `tests/test_outcome_reconciliation.py`, assert strict config loading, owner/mode checks, disjoint ID sets, source-hash validation, and rejection of missing/extra fields.

Write table-driven tests for the classifier. A valid human reply must be after an approved bot reply and satisfy all public-agent conditions. Cover requester/incoming name collisions, human before/after bot, private notes, survey source 6, excluded service accounts, null/unknown authors, no bot reply, and equal-timestamp deterministic ordering. A requester/incoming message is ignored even if its display name or numeric fixture ID collides with a human-agent fixture. No identity or conversation ID may cross the serializer.

- [ ] **Step 3: Confirm focused RED**

```bash
uv run --isolated --extra dev --locked pytest -q \
  tests/test_outcome_reconciliation.py \
  tests/test_freshdesk_csat.py \
  tests/test_cli.py
```

- [ ] **Step 4: Implement metadata-only fetch, classifier, and private cache**

Extend `FreshdeskClient` with a paginated conversations method that immediately projects each source object to a frozen metadata record. Access only `id`, `user_id`, `incoming`, `private`, `source`, and `created_at`; never interpolate a source payload into an exception or log.

The classifier first filters to public outgoing non-survey rows, sorts by parsed `created_at` then transient numeric conversation ID, finds an approved bot reply, and examines later rows. Return `true` on any approved human; otherwise return `null` if any later outgoing author is null/unknown; otherwise `false`. A known excluded author is resolved non-human and does not make the result null.

The strict cache writer uses atomic replace, directory `0700`, file `0600`, and exact-key validation. The incremental job selects only snapshot tickets whose unchanged Langfuse outcome is `ai_end_to_end`, checkpoints after each week, and refetches recent weeks within the existing fourteen-day late-response window. It emits aggregate counts only.

- [ ] **Step 5: Add CLI tests and GREEN**

Add `reconcile-freshdesk-outcomes` parser/dispatch tests, duration checkpoint/resume, sanitized 401/403/429/error behavior, recent-week refetch, old-week freeze, and proof that console/checkpoint/cache contain no conversation field or identity value.

```bash
uv run --isolated --extra dev --locked pytest -q \
  tests/test_outcome_reconciliation.py \
  tests/test_freshdesk_csat.py \
  tests/test_cli.py
```

- [ ] **Step 6: Write RED v12 projection/schema/UI tests**

Add Python and Zod fixtures covering `true`, `false`, `null`, incomplete cache, weekend exclusion in T2–T6, and missing cache. Assert strict exact keys, arithmetic bounds, `mismatch_rate` null when checked is zero, and v11 rejection after the bump.

In the CSAT section, assert exact source-faithful copy for a selected week:

```text
Đối chiếu Freshdesk: 3 trong 40 ticket “AI xử lý trọn” đã kiểm tra có CS người trả lời sau (7,5%).
2 ticket chưa xác định được tác giả và không tính vào tỷ lệ.
AI First phía trên vẫn giữ nguyên theo Langfuse.
```

When the cache is incomplete, show `Đã đối chiếu 40/50 ticket có thể kiểm tra
trên Freshdesk.`. When reconciliation is null, omit this block rather than
showing zero. Do not mention names, IDs, guard/rule, or imply `>4 lượt` caused
the reply.

- [ ] **Step 7: Implement v12 atomically and run full gate**

Load the reconciliation cache beside the CSAT cache in `web.py`, pass it into `project_dashboard`, project each view/week from that view's own session population, validate Python/Zod strictly, set `_STORAGE_VERSION = 12`, and render the scoped block in `CsatSection` using the same `effectiveWeek`/whole-period aggregation.

```bash
npm run test:unit
npm run typecheck
npm run build
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
git diff --check
```

---

### Task 6: Update the authority documents without weakening the signed privacy contract

**Files:**
- Modify: `PRODUCT.md`
- Modify: `docs/SPEC-v2.md`
- Modify: `docs/superpowers/specs/2026-08-01-freshdesk-csat-integration-design.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Documents v11 as the ticket-grain CSAT projection change and v12 as the separate observational reconciliation change.
- Preserves private cache schema v2 and the six signed redaction conditions verbatim in meaning.
- Records the user decision that Admin CS ZaloPay is the AI CS Agent for survey attribution.

- [ ] **Step 1: Add the v11 source/grain contract**

Document these exact definitions:

```text
response_count = all approved Admin CS ZaloPay survey responses in the scoped ticket cohort
ticket_count = distinct scoped tickets with at least one approved response
latest response = max(responded_at, response_key) within one Ticket ID
positive / neutral / negative = bucket of that latest response, one ticket once
by_outcome = latest-ticket counts joined to the unchanged Langfuse outcome
by_dimension.skill = latest-ticket counts joined to the normalized Skill bucket
by_dimension.issue_category = latest-ticket counts joined to normalized Category
ticket.csat_satisfaction = latest approved bucket; `unrated` only for fetched weeks; null when unfetched
feedback_entries = every approved response whose already-redacted feedback is non-null
```

State that `responded_at` sorts responses but does not select the cohort week. State that outcome, Skill, and Category rows are observational joins across two sources, not a Freshdesk rewrite of Langfuse metrics and not evidence that a dimension caused satisfaction.

In the binding Freshdesk design, add a dated v11 revision that explicitly supersedes the old dashboard-display rules at lines currently describing `response_count` as the percentage denominator and `response_count < 20` as the sample gate. Preserve `response_count` as the raw approved-response count, but state:

```text
Dashboard v11 percentage denominator = ticket_count, one latest response per ticket.
Total-row sample gate = ticket_count < 20.
Grouping-row sample gate = that row's ticket_count < 20.
response_count remains visible only as supporting context when it differs from ticket_count.
```

Do not rewrite private cache semantics: cache schema v2 still stores every approved response.

- [ ] **Step 2: Correct the product terminology**

Keep the technical private field name `comment_redacted` where the signed privacy contract names it, but add:

```text
Freshdesk exposes the source value as one `feedback` string and does not prove
whether it came from a selectable option or free typing. Browser copy therefore
uses “nội dung phản hồi”; it must not label every value “bình luận” or infer a
feedback kind without a new reviewed contract.
```

Do not delete or relax any of the six privacy conditions. Do not claim the existing redactor makes PII risk zero.

- [ ] **Step 3: Record version history and current status**

In `docs/SPEC-v2.md`, append v11 after the existing v10 history and v12 for the separate metadata-only outcome reconciliation. In `CLAUDE.md`, update the Freshdesk spec status to mention ticket-grain latest-response breakdown by outcome/Skill/Category, the latest-satisfaction Ticket Explorer column, source-faithful feedback wording, and the observational `AI xử lý trọn` reconciliation after implementation. Do not mark it implemented before Tasks 1–6 and the full gate are green.

- [ ] **Step 4: Scan for stale user-facing requirements**

```bash
rg -n "ticket_count_with_response|comments\[\]|phản hồi có bình luận|Phân trang bình luận| / .* bình luận" \
  PRODUCT.md DESIGN.md docs/SPEC-v2.md \
  docs/superpowers/specs/2026-08-01-freshdesk-csat-integration-design.md \
  frontend/src frontend/test
```

Run a second targeted scan:

```bash
rg -n 'Mẫu số là `response_count`|response_count < 20|dưới 20 response|20 response' \
  PRODUCT.md docs/SPEC-v2.md \
  docs/superpowers/specs/2026-08-01-freshdesk-csat-integration-design.md CLAUDE.md
```

Expected: no active dashboard-display requirement still uses response grain. Historical text may remain only inside a clearly marked superseded section. No stale browser-contract key or user-facing “bình luận” copy remains. Technical historical references to the signed `comment_redacted` privacy exception may remain and must be clearly labeled as private-contract terminology.

---

### Task 7: End-to-end, privacy, and live-data acceptance

**Files:**
- Modify: `frontend/e2e/dashboard.spec.ts`
- Do not commit: `runtime/dashboard_snapshot.json`
- Do not modify: `runtime/csat_cache.json`

**Interfaces:**
- Uses fixture E2E first, then one bounded local live verification.
- Produces no screenshots or exported payload containing feedback text unless the user explicitly asks for an artifact.

- [ ] **Step 1: Add a fixture E2E for the critical decision path**

Route a v12 envelope in `frontend/e2e/dashboard.spec.ts`. Verify:

1. Default T2–T6 and latest-week CSAT table uses ticket grain.
2. Breakdown rows are not buttons. Selecting `AI xử lý trọn` from the explicit feedback filter activates the global outcome chip, filters feedback entries, and updates Ticket Explorer.
3. Selecting `Tất cả` clears all three surfaces.
4. Switching to Skill clears the outcome selection; selecting `Nhiều skill` filters both feedback and Ticket Explorer to multi-skill tickets rather than `Chưa ghi nhận` tickets.
5. Switching to Category replaces the Skill rows; more than 10 rows are collapsed until `Xem tất cả N nhóm` is activated.
6. Opening 23 feedback entries renders 10 on page 1 and 3 on page 3.
7. A repeated ticket displays sequence/latest metadata.
8. Ticket Explorer shows `Mức độ hài lòng (CS Agent)` by default; `negative` renders `Rất tệ`, `unrated` renders `Chưa có đánh giá`, and `null` renders `—`.
9. Filtering `Rất tệ` updates the active chip and results; clearing it restores all rows.
10. In `So sánh theo thuộc tính ticket`, a `Chưa ghi nhận` bucket with `total=0` is absent while a positive-total row with zero child metrics remains.
11. No user-facing `bình luận` or raw internal outcome/satisfaction code is visible.
12. The reconciliation block distinguishes checked, unresolved, and not-yet-fetched tickets; it never changes the Langfuse KPI and never exposes an author identity.

- [ ] **Step 2: Run all deterministic gates**

```bash
npm run test:unit
npm run typecheck
npm run build
npm run test:e2e
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
git diff --check
```

Expected: all pass. Do not report Docker as verified.

- [ ] **Step 3: Regenerate a v13 snapshot and reconciliation cache through normal commands**

Start the local dashboard through the normal command in one terminal:

```bash
.venv/bin/weekly-cs-dashboard --local --port 8765
```

In the verification terminal, first wait for the API to produce a readable v13 snapshot, then run the bounded metadata-only reconciliation job. After the job publishes its private cache, record the snapshot mtime and request one explicit refresh through the normal protected route; do not edit runtime JSON manually:

```bash
until curl -fsS http://127.0.0.1:8765/api/dashboard >/dev/null; do sleep 1; done

.venv/bin/weekly-cs-report reconcile-freshdesk-outcomes \
  --weeks 13 --max-workers 1 --max-duration 7200 \
  --runtime-dir "$(pwd)/runtime"

snapshot_mtime_before="$(stat -f %m runtime/dashboard_snapshot.json 2>/dev/null || echo 0)"
curl -fsS -X POST \
  -H 'X-Dashboard-Action: refresh' \
  http://127.0.0.1:8765/api/refresh >/dev/null

for attempt in $(seq 1 120); do
  snapshot_mtime_after="$(stat -f %m runtime/dashboard_snapshot.json 2>/dev/null || echo 0)"
  if [ "$snapshot_mtime_after" -gt "$snapshot_mtime_before" ] && \
     jq -e '.schema_version == 13 and (.generated_at | type == "string")' \
       runtime/dashboard_snapshot.json >/dev/null; then
    break
  fi
  sleep 1
done

test "$snapshot_mtime_after" -gt "$snapshot_mtime_before"
jq '{schema_version, generated_at}' runtime/dashboard_snapshot.json
```

The reconciliation command must report only aggregate completion counts, and the server terminal must show the structured `refresh_success` event for the subsequent request. A pre-existing `200` alone is not regeneration proof. If current Langfuse/Freshdesk access is unavailable, either cache cannot be published, the mtime does not advance, schema is not `12`, or `refresh_success` is absent, report the unavailable live gate; fixture tests are not a substitute for live proof.

- [ ] **Step 4: Run aggregate reconciliation and privacy checks**

```bash
curl -fsS http://127.0.0.1:8765/api/dashboard | jq '[.snapshot.views.mon_fri.csat.by_week[]? |
  select(. != null) |
  {
    response_count,
    ticket_count,
    latest_buckets: (.positive + .neutral + .negative),
    outcome_tickets: ([.by_outcome[].ticket_count] | add),
    skill_tickets: (([.by_dimension.skill[].ticket_count] | add) // 0),
    category_tickets: (([.by_dimension.issue_category[].ticket_count] | add) // 0)
  }
]'

for endpoint in \
  'http://127.0.0.1:8765/api/dashboard' \
  'http://127.0.0.1:8765/api/tickets?page=1&page_size=100'; do
  curl -fsS "$endpoint" | jq --argjson forbidden '[
    "UserID", "TransID", "traceId", "sessionId",
    "agent_id", "agent_name", "user_id", "group_id",
    "survey_id", "rating_id", "rating_raw", "comment_present",
    "response_key", "response_id", "source_hash", "response_hash",
    "feedback", "body_text", "attachments", "raw_comment"
  ]' '[
    paths as $path
    | ($path[-1] | tostring) as $key
    | select($forbidden | index($key))
  ] | length'
done

for endpoint in \
  'http://127.0.0.1:8765/api/dashboard' \
  'http://127.0.0.1:8765/api/tickets?page=1&page_size=100'; do
  curl -fsS "$endpoint" | grep -cE 'UserID|TransID|traceId|sessionId' || true
done

stat -f "%Sp %N" .env runtime runtime/csat_cache.json \
  runtime/outcome_reconciliation_cache.json runtime/dashboard_snapshot.json
```

Expected for every week: `latest_buckets == outcome_tickets == skill_tickets == category_tickets == ticket_count`, and `response_count >= ticket_count`. Each recursive forbidden-key scan and each required sensitive-token grep prints `0`; the exact-key scan avoids confusing allowed `feedback_entries` with forbidden raw `feedback`. Permissions remain `.env -rw-------`, runtime `drwx------`, both caches `-rw-------`. Both payloads are streamed to the checks and are not copied to another file.

- [ ] **Step 5: Verify the real UI at desktop and mobile**

At `1440×900` and `390×844`, light and dark:

- Confirm the same cohort/week label and denominator govern the CSAT total, the currently selected outcome/Skill/Category rows, and the feedback list.
- Confirm the default row shows latest-ticket counts, while detail can contain more responses than tickets.
- Confirm one grouping at a time, the 10-row dimension collapse, read-only breakdown rows, the explicit `Tất cả`/value feedback selector, active filter chip, Ticket Explorer filter, satisfaction/week/time filters, pagination, Freshdesk links, sequence labels, and focus retention.
- Confirm Ticket Explorer's default satisfaction column, four actionable filter values, semantic badge colors plus text, `unrated` versus unfetched `—`, semantic sort order, and CSV wording.
- Confirm every segment dimension hides `total=0` rows and still shows a `total>0` row whose AI First/Chuyển CS/Reopen values are all zero.
- Confirm horizontal overflow exists only inside the intentional table scroller; tap targets are at least 44×44.
- Run axe and accept no serious/critical violation, console error, CSP error, or external network request.

- [ ] **Step 6: Final acceptance report**

Report each item as `ĐẠT` or `CHƯA`, with real command output:

1. Latest response per ticket is the only headline/outcome/Skill/Category denominator.
2. All historical redacted feedback responses remain browsable 10 per page.
3. Outcome, Skill, and Category tables each reconcile exactly and share active cohort/week scope.
4. Only one grouping is visible at a time; its explicit clearable selector controls both feedback and the matching existing Ticket Explorer filter.
5. UI uses “nội dung phản hồi”, not a fabricated free-text/option distinction.
6. Admin CS ZaloPay remains the only included survey agent.
7. Ticket Explorer satisfaction uses the same latest response, distinguishes `unrated` from unfetched data, and filters/exports only safe labels.
8. v11 CSAT, v12 reconciliation, and v13 ticket-opened-at strict Python/Zod
   parity pass; v12 snapshots are rejected by the final v13 loader.
9. Zero-ticket segment placeholders are absent without hiding positive-total rows.
10. PII key scans, permissions, unit, typecheck, build, E2E, Python, axe, and responsive checks pass.

Do not commit, push, publish, or modify Freshdesk/Langfuse external state as part of this plan.

---

## Explicit Non-goals and Deferred Decision

- No Freshdesk ticket stats, resolution-time metric, comment taxonomy, response-rate metric, or human-CS survey.
- No change to `AI xử lý trọn`: it still means Langfuse observed a substantive AI first response and no later canonical transfer response.
- No assumption that `ai_end_to_end` means no later Freshdesk agent response.
- Reconciliation calls a reply “CS người” only for IDs materialized from the PO-approved Freshdesk agent roster. Unknown/null authors remain `không xác định`; display names are never used at runtime or exposed.
- A `>4 lượt trả lời` ticket can be either `ai_end_to_end` or `ai_then_cs`: only an observed canonical transfer response changes the outcome.

---

## Steer bổ sung 2026-08-03 — dashboard v13

Correction này supersede mọi bước cũ khi mâu thuẫn, nhưng không đổi cache
Freshdesk v2 hay reconciliation cache v1:

1. `TicketRow` thêm `opened_at` canonical UTC từ
   `SessionMetrics.turn0_timestamp`; Ticket Explorer hiển thị ngày giờ Việt
   Nam, CSV dùng cùng format và backend sort toàn cục trước pagination. Không
   thêm filter ngày giờ riêng vì filter tuần đã là control thời gian chính.
2. Khôi phục bảng điều kiện hệ thống và bảng ticket quá 4 lượt trong mục chẩn
   đoán. Bảng điều kiện dành cho Dev nên cột `Giá trị nguồn` hiện nguyên văn
   rule như `cs_escalation`, không diễn giải. Bảng >4 chỉ hiện `Tổng`, `Đã chuyển
   CS`, `Chưa chuyển CS` và action mở Explorer. Ngoài bảng Dev, không hiện
   `max_replies_rule_fired`, “rule bắn”, “khoảng trống rule” hay “guard chặn”.
   Panel `escalation_guard_blocked` tiếp tục ẩn vì bị đọc ngược nghĩa và không
   tạo hành động riêng.
3. Hai bảng dùng cùng `effectiveWeek` với KPI/segment; chỉ `Xem toàn kỳ` mới
   dùng aggregate toàn kỳ. Action chưa chuyển giữ filter tuần đang chọn.
4. Dòng nguồn CSAT là một câu duy nhất trên desktop:
   `CSAT: Freshdesk · chỉ Admin CS ZaloPay · cập nhật <thời gian> · Dữ liệu
   khác: Langfuse.` Trạng thái stale nối cuối cùng trên cùng dòng; mobile được
   wrap tự nhiên.
5. Dashboard storage/browser bump v12 → v13 trong cùng batch với exact-key
   Python và strict Zod. Snapshot v12 phải bị từ chối; dữ liệu Freshdesk và
   Langfuse không đổi công thức.
6. Không render khối `Đối chiếu Freshdesk` hoặc các dòng coverage/phương pháp
   của `outcome_reconciliation` trên dashboard. Cache và payload v12 vẫn giữ
   nguyên để tương thích; thay đổi này chỉ bỏ presentation.
