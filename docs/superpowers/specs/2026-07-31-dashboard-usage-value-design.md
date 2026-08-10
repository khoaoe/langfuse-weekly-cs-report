# Dashboard Usage-Value Design

**Date:** 2026-07-31
**Revised:** 2026-07-31 after implementer re-verification (see Revision log)
**Status:** Batches 1, 2 and 4 implemented; Part C deferred by PO
**Scope:** Presentation copy, same-period comparison, skill-change timeline.
No metric formula, no outcome definition, and no Weekly Report column changes.

**PO delivery decision — 2026-07-31:** ship Batches 1, 2 and 4. Keep
`CS_AGENT_ENABLED=false`. Batches 3 and 5–8 are not authorized until the PO
explicitly resumes Part C.

## Revision log

The implementer re-verified every measurement before writing code, as AGENTS.md
requires, and returned one false figure plus seven design contradictions. All
are corrected below. They are recorded because the corrections change the
implementation order, not only the prose.

| # | Finding | Correction |
|---|---|---|
| 1 | **E3 overstated final coverage as 98%.** Recomputed from the schema-v5 snapshot: week 2026-07-27 is 83.3%. 98.1% is the interbank skill's *AI-first rate*, a different quantity that was conflated | E3 table corrected below. **R4's verdict is unchanged** — coverage still moves 0.3% → 83%, far past the 0.10 stability threshold |
| 2 | `same_period` sat at payload top level, but the payload carries two cohort views (`mon_fri`, `mon_sun`) that cannot share one block | `same_period` moves inside each `views.<week_definition>`, built by `_view_payload()` |
| 3 | Batch 4 added payload keys while the v5 → v6 bump sat in Batch 6, changing a persisted schema without changing its version | Batch 4 bumps v5 → v6. Batch 6 bumps v6 → v7 |
| 4 | `same_period.by_week` was defined as complete weeks only, yet the chart toggle must draw the running week too | `by_week` includes the current truncated WTD row explicitly |
| 5 | Batch 5 was labelled "payload unchanged" but its isolation test asserted `skill_timeline.status`, a Batch 6 field | Batch 5 asserts refresh success only; the status assertion moves to Batch 6 |
| 6 | Batch 1's coverage warning read global `snapshot.coverage.skill` while the table may be scoped to a selected week | The warning derives numerator, denominator and threshold from the rendered segment scope |
| 7 | The cutoff rule left Monday and partial-day behaviour undefined | Cutoff is the last **fully completed** Asia/Ho_Chi_Minh day. On Monday, `same_period` is `null` |
| 8 | `skill_changelog.v{n}.bak` could overwrite an existing backup of the same version, contradicting "never overwrite" | Backup names carry a UTC timestamp and are created with `O_CREAT \| O_EXCL` |

Accepted without change: E4's `withdraw` peak is 42 rather than 41 — the
conclusion that interbank is the only viable comparison stands. The snapshot
read for E3 now lives in `.private-quarantine/`; treat the figures below as the
recorded measurement, and re-measure from a fresh snapshot when one exists.

## Problem

The dashboard is technically sound — invariants hold, the chart law is
enforced, the PII boundary is tight, accessibility passes. A usage-value
stress test against the PO's actual weekly CS report found the gaps are
elsewhere.

1. **Skill edits cannot be measured.** The PO edits CS-agent skills on
   `cs-agent.zalopay.vn`, then has no way to tell whether the following week
   improved. Nothing records which skill changed when, so no before/after
   comparison is possible. This is the primary complaint.
2. **The running week is refused a comparison.** `narrative.ts` prints
   `"tuần đang chạy nên chưa so với tuần đủ"` — declining to answer, while a
   same-period comparison (Mon–Wed this week against Mon–Wed of prior weeks)
   is computable from data already in the snapshot.
3. **Several user-facing strings carry no information.** Live example:
   `"Độ phủ Skill mới 50,9% — Đọc phần so sánh segment kèm cảnh báo độ phủ,
   đừng suy rộng cho toàn bộ ticket."` It instructs the reader not to do
   something instead of telling them what is true. The audience is the CS
   team, not the people who built the pipeline.
4. **The attention rail mixes two kinds of warning.** ">4 turn stuck"
   (actionable) sits beside "coverage 50.9%" (data trustworthiness), which
   dilutes the warning that needs action.
5. **`skill` is a payload dimension that is never rendered.** The frontend
   exposes 4 of 8 segment dimensions.

Target outcome: CS opens the dashboard and immediately reads whether this week
is better or worse; the PO can answer "did the skill edit help"; the dev team
still sees the rule-enforcement hole.

**Out of scope:** reopen-reason labelling. It remains blocked at the human
golden-labelling gate (`2026-07-30-reopen-reason-labeling-design.md` §10 step
13). This spec only records where that dimension plugs in later.

## Measured evidence

### E1 — The cs-agent API has no history

`https://cs-agent.zalopay.vn/openapi.json` is public and was read directly.
28 paths. There is no `/history`, `/versions`, or `/audit` endpoint. `SkillInfo`
carries no `updated_at`. Only `SkillPatch.updated_by` exists, and it is
write-only.

Skill-related paths:

```
GET            /api/skills
POST           /api/skills/{skill_id}
GET,PUT        /api/skills/{skill_id}/guardrails
POST           /api/usecases
GET            /api/usecases/{skill_id}/form
DELETE,PUT     /api/usecases/{skill_id}
GET            /api/usecases/form-meta | /template
POST           /api/usecases/parse | /preview | /validate
```

History must therefore be **synthesized** by polling the read endpoints and
hashing content. This captures changes from activation onward only. Past
changes are unrecoverable.

### E2 — `skill` is already aggregated per week

`_SEGMENTS` (`dashboard_schema.py:52-61`) already contains `skill`, and
`by_week[weekISO].segments.skill[label] = {total, ai_first, transferred,
reopen}` exists for every cohort week. Before/after analysis is a join of
change timestamps against data already computed. No new aggregation, no new
metric.

### E3 — Skill coverage is unstable, and this invalidates naive comparison

Measured from the schema-v5 snapshot generated `2026-07-31T04:33:01Z`,
`views.mon_fri.by_week[*].segments.skill`. That file now sits in
`.private-quarantine/`; re-measure from a fresh snapshot when one exists.

| Cohort week | Total | `interbank-fund-transfer` | `Không xác định` | Skill coverage |
|---|---:|---:|---:|---:|
| 2026-06-29 | 610 | 2 | 608 | 0.33% |
| 2026-07-06 | 1,139 | 11 | 1,126 | 1.14% |
| 2026-07-13 | 1,171 | 611 | 533 | 54.48% |
| 2026-07-20 | 1,249 | 930 | 192 | 84.63% |
| 2026-07-27 (WTD) | 810 | 587 | 135 | 83.33% |

Coverage runs 0.33% → 1.14% → 54.5% → 84.6% → 83.3%. The headline "skill
coverage 50.2%" is an average that hides this.

Do not confuse this with the interbank skill's own AI-first rate, currently
about 98.1%. An earlier draft of this spec conflated the two and claimed 98%
coverage. Coverage and per-skill AI-first rate are different quantities.

Consequence: **any before/after delta spanning this boundary is dominated by
instrumentation rollout, not skill quality.** A change on 2026-07-10 would show
`interbank-fund-transfer` AI-first moving from a base of 11 tickets to one of
930 — a non-comparable population. If the PO reads the resulting delta as "the
fix worked", the dashboard has caused a wrong decision. Rule R4 in §C4 exists
specifically to refuse this. Against a 0.33% → 84.6% swing it refuses every
comparison currently available, which is the correct output.

### E4 — Only four skill labels exist, one dominates

Observed labels: `interbank-fund-transfer`, `topup`, `withdraw`,
`topup-withdraw`. Peaks: interbank 930, topup 111, withdraw 42,
topup-withdraw 26. Only `interbank-fund-transfer` (587–930/week) can support a
rate comparison; the rest sit far below R5's 100-ticket floor. The UI must not
imply a rich multi-skill comparison exists.

### E5 — Skill bodies are free prose and are a PII vector

`UsecaseForm` fields `description`, `processing_flow`, `response_structure`,
`global_template`, `escalate_template[]`, `response_principles[]`, and
`scenarios[].{trigger, condition, response_template, sub_skill_description,
tool_notes_text, steps[].description}` are all free-form Vietnamese prose
authored by the PO. Such content routinely embeds example customer utterances
and transaction-code formats. **No `UsecaseForm` field may be serialized to the
browser.** Content is hashed server-side and the plaintext discarded in the
same function scope.

### E6 — Storage version is 5

`_STORAGE_VERSION = 5` (`dashboard_schema.py:23`), not 4. Building against 4
would break `from_storage_dict`.

### E7 — Do not backfill from local skill files

`docs/skill/<domain>/` holds `v1.json`, `v2.json`, `v3.json` — evidence the PO
versions skills by hand. File mtime does not prove production deploy time.
Backfilling from mtime would fabricate exactly the timestamps this feature
exists to establish.

## Locked decisions

| D | Decision |
|---|---|
| **D1** | Timeline is synthesized by polling `GET /api/skills` and `GET /api/usecases/{id}/form`, hashing canonicalized content, and recording a change when the digest differs |
| **D2** | The cs-agent source is a separate, fail-closed module. If it is unreachable or unconfigured, the dashboard behaves exactly as today and only loses the annotation layer. No new runtime dependency — the existing `httpx` is reused |
| **D3** | Change markers render as vertical lines on the existing trend charts, plus a before/after table |
| **D4** | One page is kept. One section is added (nav goes from 6 to 7 items). No new route, no tabs, no role filter |
| **D5** | The running week compares against the same-period mean of the 4 most recent complete weeks. **The trend charts get a "Same period / Full week" toggle. The 14-column Weekly Report does not** |
| **D6** | All user-facing copy is rewritten. Any string that cannot answer "what does a CS reader learn from this" is deleted, not reworded |
| **D7** | The attention rail keeps only actionable warnings. Trustworthiness warnings move next to the number they qualify |

**Why the table has no toggle (D5).** The 14-column table is the artifact
exported to the CS team. If a single button turns `1,249` into `731` under the
same `20/07 · Tổng ticket` label, a truncated figure reaches the CS sheet
undetected; `weekly-export.ts` carries only one cohort preamble today. Further,
truncating a closed week to Mon–Wed discards three days of real data — in
same-period mode 12 of 13 rows become numbers manufactured for a comparison
rather than the truth of that week. The charts are the opposite case: not
exported, not a contract, and truncating every week equally stops the final
column from dipping merely because the week is unfinished.

---

## Part A — Copy rewrite

Rule applied to every string: **state the number and what is missing; do not
instruct the reader to refrain from something.** Delete any string that cannot
answer "what does a CS reader learn from this".

Removed from the UI entirely: `"Cần lưu ý"`, `"đừng suy rộng"`, `"không tự suy
luận nguyên nhân"`, `"chỉ chẩn đoán trên phần dữ liệu quan sát được"`.

### A1 — `frontend/src/lib/narrative.ts`

Drop the `WTD_NOT_COMPARABLE` constant. Part B supplies the replacement figures.

| Current | Replacement |
|---|---|
| `AI First 78,0% (627 ticket), tuần đang chạy nên chưa so với tuần đủ.` | `AI First 78,0% (627 ticket). Tính tới thứ Tư, cùng kỳ 4 tuần trước trung bình 74,2% — tuần này đang nhỉnh hơn 3,8 điểm.` |
| `Reopen sau AI First 18,8%, tuần đang chạy nên chưa so với tuần đủ.` | `Reopen sau AI First 18,8%, cùng kỳ 4 tuần trước 21,5%.` |
| `Cần xử lý: 12 ticket quá 4 turn nhưng chưa chuyển CS — user có thể đang kẹt.` | `12 ticket đã quá 4 lượt trả lời mà chưa chuyển CS — khách nhiều khả năng đang mắc kẹt.` |
| `Cần lưu ý: Thiếu dữ liệu bổ sung lần đọc này — Intent, Skill, Guardrail và Step result có thể chưa đầy đủ.` | `Lần đọc này chưa lấy đủ dữ liệu phụ, nên Intent, Skill, Guardrail và Step result còn thiếu.` |

Complete weeks keep `"tăng/giảm N điểm so với tuần trước"`. That sentence
already works. The `"điểm"` unit convention is unchanged.

### A2 — `frontend/src/lib/selectors.ts`, `selectAttentionItems` (:329-400)

The rail keeps only warnings a reader can act on.

Kept:

- `attention-gt4` → headline `"12 ticket quá 4 lượt trả lời mà chưa chuyển CS"`,
  action `"Mở Ticket Explorer, lọc >4 turn để xem từng ticket."`
- `attention-gate` → headline `"8,2% bản ghi lỗi cấu trúc, vượt ngưỡng 5%"`,
  action `"Số tuần này chưa dùng để ra quyết định. Kiểm tra pipeline trước."`
- `attention-enrichment` → stays (it clears on the next refresh) but is
  reworded: headline `"Lần đọc này chưa lấy đủ dữ liệu phụ"`, action
  `"Chờ lần làm mới kế tiếp rồi hãy kết luận theo Intent, Skill, Guardrail hay
  Step result."`

Moved, not deleted:

- `attention-coverage` → into the Skill tab of the segment table (A3)
- `attention-step-result` → into the Transfer diagnostics section (A3)

An empty rail means a healthy week. That is the goal.

### A3 — Trustworthiness warnings, placed beside the affected number

**Skill tab (`BelowFold.tsx`)**:

```
Bảng dưới chỉ tính 634/1.249 ticket có ghi nhận skill. 615 ticket còn lại agent
chưa gắn skill nên không nằm trong bảng này.
```

Real numerator and denominator. No instruction.

**The numbers come from the segment data actually rendered**, never from global
`snapshot.coverage.skill`. The segment table is week-scoped — when a week is
cross-filtered it reads `view.by_week[activeWeek].segments`
(`BelowFold.tsx:627-629`) — so a global coverage figure would describe a
different population than the rows on screen, and E3 shows those populations
differ by up to 84 points. Derive all three from the rendered bucket map:
denominator is the sum of `total` across buckets, the missing count is the
`"Không xác định"` bucket's `total`, and the line renders when
`1 − missing/denominator < 0.8`. A zero denominator renders nothing.

**Transfer diagnostics (`TransferDiagnostics.tsx`)**, when Step result is
missing:

```
160/208 ticket chuyển CS (76,9%) không có Step result. Phần lớn ca chuyển CS
hiện chưa truy được tới bước lỗi cụ thể.
```

This is a significant finding — three quarters of transfers cannot be traced to
a failing step — but the current wording turns it into methodological advice,
so no reader reacts to it.

### A4 — `DataQualitySection.tsx`, `coverageConsequence` (:27-43)

| Current | Replacement |
|---|---|
| `13% ticket không có Transstatus nguồn; chẩn đoán chuyển CS chưa bao phủ phần này.` | `13% ticket không có Transstatus, nên phần này không truy được nguyên nhân chuyển CS.` |
| `49,1% ticket chưa ghi nhận skill; không dùng phần này để kết luận toàn kỳ.` | `49,1% ticket agent chưa ghi nhận skill nào.` |
| `23,2% ticket chưa có Intent an toàn để hiển thị.` | `23,2% ticket có Intent quá hiếm hoặc không đúng định dạng an toàn, gom vào "khác".` |

### A5 — Sweep the remaining strings

Review every user-facing string literal under `frontend/src/`. For each, ask
what a CS reader learns. If there is no answer, delete the string. Covers KPI
labels, chart captions, empty states, error states, column headers,
`#howToReadPanel`, and nav labels.

`DESIGN.md` and `docs/SPEC-v2.md` §5 record fixed copy. Any string changed here
updates those documents **in the same commit**.

---

## Part B — Same-period comparison for the running week

Feasibility is confirmed: every ticket carries its own `cohort_week`
(`dashboard_schema.py:79`), so restricting each past week to "Monday through the
current weekday" is a filter over sessions the pipeline already has. No new data
source and no new formula.

### Backend

**Placement.** `same_period` lives **inside each view**, not at payload top
level. The payload already carries two cohort definitions
(`views.mon_sun`, `views.mon_fri`, `_VIEWS` at `dashboard_schema.py:51`) whose
week boundaries differ, so one shared block cannot describe both. It is built by
`_view_payload()` (`dashboard_schema.py:390-391`) alongside `weekly` and
`by_week`, and validated against the per-view key set — `_DASHBOARD_KEYS`
(`:71`) is untouched.

```jsonc
"views": {
  "mon_fri": {
    "weekly": [ /* unchanged */ ],
    "by_week": { /* unchanged */ },
    "same_period": {
      "cutoff_date": "2026-07-29",   // last FULLY COMPLETED local day
      "cutoff_weekday": 3,           // 1=Mon … 7=Sun, derived from cutoff_date
      "current": {
        "cohort_week": "2026-07-27",
        "total_tickets": 804, "ai_first_count": 627, "ai_first_rate": 0.780,
        "reopen_lifetime_rate": 0.188,
        "reopen_lifetime_numerator": 118, "reopen_lifetime_denominator": 627
      },
      "baseline": { "weeks_used": 4, "ai_first_rate": 0.742, "reopen_lifetime_rate": 0.215 },
      "by_week": {
        "2026-07-27": { /* same shape as current — the running week, included */ },
        "2026-07-20": { /* truncated complete week */ }
      }
    }
  },
  "mon_sun": { /* its own same_period, computed on its own week boundaries */ }
}
```

**Cutoff rule.** `cutoff_date` is the last **fully completed** day in
`Asia/Ho_Chi_Minh` — that is, `as_of.date() - 1 day` whenever `as_of` falls
inside a day, so a partially elapsed today never enters either side of the
comparison. Consequences, all explicit:

- If `cutoff_date` precedes the running week's Monday — that is, the running
  week has no completed day yet — `same_period` is `null`. On a Monday this is
  always the case.
- A complete current week (no WTD) also yields `same_period: null`.
- When `same_period` is `null` the narrative keeps its existing week-over-week
  sentence and the chart toggle does not render.

**Computation.**

- Every week, running and historical alike, is truncated to
  `[Monday 00:00, cutoff_weekday 23:59:59]` in local time before aggregation.
- `baseline` is the mean over the 4 most recent **complete** weeks so truncated.
  Weeks without data are skipped, not counted as zero; `weeks_used` reports how
  many actually contributed, and `same_period` is `null` when fewer than 2
  qualify.
- **`by_week` contains the running truncated week as well as the truncated
  complete weeks.** The chart toggle draws every week from this map, so omitting
  the running week would drop the very column the comparison exists to explain.
- Reuse `_summarize_sessions` over the date-filtered session set. Do not write a
  second implementation of any metric.

### Frontend

- `narrative.ts` consumes `views[weekDefinition].same_period.baseline` (A1) —
  the block for the cohort the reader currently has selected, never the other
  one.
- **Chart toggle** in `BelowFold.tsx`: a two-state control
  `[Cùng kỳ đến T4 | Tuần đủ]` above the two panels, defaulting to
  **Tuần đủ** (today's behaviour). Selecting same-period redraws every week —
  including the running week — from `same_period.by_week`. The control renders
  only when the active view's `same_period` is non-null, and it resets to
  **Tuần đủ** when the cohort toggle changes, because the two views' cutoffs can
  differ.
- The toggle switches both panels together so the shared x-axis stays aligned.
- The chart caption follows the state:
  `"Mọi tuần đều cắt tới thứ Tư để so cùng kỳ."`
- **The 14-column table is untouched.** `weekly-export.ts` is not modified.

---

## Part C — Skill-change timeline and before/after impact

### C1 — Change-history store

New module `src/weekly_cs_report/skill_timeline.py`; new file
`runtime/skill_changelog.json`, mode `0600` inside the existing `0700`
`runtime/` directory. Reuse the exact atomic-write recipe from
`ProtectedSnapshotStore.save()`: `tempfile.mkstemp(dir=...)` →
`os.fchmod(fd, 0o600)` → `json.dump(sort_keys=True)` → `flush` → `os.fsync` →
`os.replace`.

```jsonc
{
  "schema_version": 1,
  "updated_at": "2026-08-07T03:00:00Z",
  "skills": {
    "customer-service/withdraw": {
      "content_digest": "<sha256 hex>",
      "observed_at": "2026-08-07T03:00:00Z"
    }
  },
  "events": [
    {
      "skill_label": "withdraw",
      "plugin_name": "customer-service",
      "detected_at": "2026-08-07T03:00:00Z",
      "cohort_week_mon_fri": "2026-08-03",
      "cohort_week_mon_sun": "2026-08-03",
      "change_kind": "content"
    }
  ]
}
```

- Never contains skill body text. Digests only.
- Retention: at most 500 events, and nothing older than 400 days. Both bounds
  enforced on write, capping the file near 120 KB.
- On `schema_version` mismatch, JSON error, or validation failure: emit
  `skill_changelog_ignored`, **rename the file aside**, and start empty. Never
  crash, never partially convert, never overwrite. This differs deliberately
  from the snapshot recipe — a snapshot is rebuildable, history is not.
- **Backup names must not collide.** `skill_changelog.v{n}.bak` alone would let
  a second failure of the same version destroy the first backup, contradicting
  the rule above. Use `skill_changelog.v{n}.{YYYYMMDDTHHMMSSZ}.bak` and create
  it with `O_CREAT | O_EXCL`; on the rare same-second collision, append a
  counter until the open succeeds. If no name can be claimed, leave the original
  file untouched, emit the event, and run with an empty in-memory log — losing
  new detection is acceptable, destroying recorded history is not.

### C2 — Canonicalization and hashing

Hashing a whole response produces false positives. The rules:

1. **Recursive field allowlist.** Only these contribute:
   `plugin_name`, `usecase_name`, `description`, `processing_flow`,
   `response_structure`, `global_template`, `tools`, `tool_notes`,
   `escalate_template`, `response_principles`, `sub_skill_ref_order`,
   `sub_skill_group_map`, and within `scenarios[]`: `trigger`, `condition`,
   `tools`, `response_template`, `sub_skill_description`, `tool_notes_text`,
   `steps[].{order, description}`, `sub_scenarios[]`.
   Anything else — including fields the API adds later — is ignored, so a new
   field cannot manufacture a phantom change. `sub_skill_file` is excluded: it
   is a path and churns on re-save without semantic change.
2. **Normalization** before hashing: `unicodedata.normalize("NFC", …)`, strip
   each string, collapse internal whitespace runs to one space, and drop keys
   whose value is `None`, `""`, `[]`, or `{}` so absent and empty hash alike.
3. **Stable serialization:**
   `json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`
   then `hashlib.sha256(...).hexdigest()`. Order is preserved where it is
   semantic (`scenarios`, `steps`, `sub_skill_ref_order`); `tools` is sorted.
4. Guardrails hash separately from `GET /api/skills/{id}/guardrails`, producing
   `change_kind: "guardrail"`, so a guardrail tweak is distinguishable from a
   body rewrite.

**Mandatory gate before this is trusted** — Batch 3's acceptance criterion:

```bash
.venv/bin/weekly-cs-report skill-timeline-probe --repeat 3 --interval 60
```

The probe prints skill label, digest, and equal/differs — never body text.
**Three consecutive polls over at least two minutes must produce byte-identical
digests for every skill.** If any digest flaps, the allowlist is wrong and the
feature does not ship. A false marker on a chart is worse than no timeline.

**First-poll behaviour:** a skill with no prior digest records its digest and
emits **no event**. `change_kind: "added"` applies only when the changelog has
already completed at least one prior poll. Day one must not produce a wall of
phantom markers.

### C3 — Poller isolation

The poll does **not** ride along with the dashboard refresh.
`_ENRICHMENT_BUDGET_SECONDS = 110.0` inside a 120 s deadline leaves no room, and
`SnapshotManager._refresh` treats any exception from the loader as a failed
refresh — so a cs-agent hiccup inside `load_snapshot` would push the dashboard
to `stale_error`. That violates D2.

- A `SkillTimelinePoller` owning its own timer-driven loop, started from
  `create_app`'s `lifespan` (`web.py:125`) and stopped alongside
  `manager.close()`.
- **Cadence 15 minutes**, jittered ±60 s. Skill edits are human-paced; 15
  minutes is far finer than the weekly grain that consumes the result.
- **Budget 20 s per cycle**, enforced by `httpx.Timeout(connect=5, read=8,
  write=5, pool=5)` plus a monotonic deadline checked between skills. At most 12
  detail calls per cycle. On deadline the cycle ends and remaining skills carry
  to the next one. A partial cycle records what it read and **never** emits
  `removed` events for skills it did not reach.
- **Three independent barriers:** (1) the poller never touches
  `SnapshotManager`, the snapshot store, or `load_snapshot` — separate thread,
  file, and lock; (2) the entire poll body is wrapped in `try/except Exception`
  that can only `emit_event` and return; (3) the dashboard read path returns an
  **empty annotation payload** on any error, so a corrupt, locked, or absent
  changelog degrades to "no markers", never to a failed refresh.
- Required test:
  `test_skill_timeline_isolation.py::test_dashboard_refresh_succeeds_when_cs_agent_is_unreachable_and_slow`
  — a poller pointed at a socket that accepts and never responds, asserting a
  full refresh completes and `/api/dashboard` returns 200 with a payload byte-
  identical to a run with no poller at all. **In Batch 5 the test asserts refresh
  success only**; `skill_timeline` does not exist in the payload until Batch 6,
  so asserting `status == "unavailable"` belongs there. Batch 6 extends the same
  test with that assertion.

### C4 — Attribution semantics

Following the established `"tín hiệu chuyển CS"` precedent, which never asserts
cause from overlapping observational signals:

> The dashboard never says a change caused an outcome. It says: the skill
> changed at this point, and the numbers before and after looked like this.
> Two facts placed side by side; the reader supplies the judgement.

| Rule | Content |
|---|---|
| **R1** | The week containing the change is excluded from **both** sides, always, and is labelled as excluded. Non-negotiable |
| **R2** | Both sides require `cohort_status == "complete"` and `has_data == true`. A WTD week is never used |
| **R3** | Minimum 2 complete weeks per side (`W-2, W-1` / `W+1, W+2`). Fewer → **no delta** |
| **R4** | **Coverage-stability gate (from E3).** For every week on both sides, that week's skill missing-share must stay within 0.10 of the reference week's missing-share, the reference being the first eligible BEFORE week. Any failure → **no delta**, reason `"Độ phủ Skill hai kỳ chênh nhau quá nhiều, không so được"` |
| **R5** | Minimum 100 tickets for that skill on each side, aggregated across the two weeks. Below that, counts only, no rate delta. At n=100 the 95% CI on a proportion near 90% is roughly ±6 points, so smaller samples cannot support a better/worse claim |
| **R6** | Two or more changes for one skill inside a single window collapse into one row, reason `"Nhiều thay đổi trong cùng kỳ, không tách được"` |
| **R7** | A fixed context sentence renders adjacent to every delta, never in a tooltip |

R7 text:

> Đây là quan sát trước và sau, không phải bằng chứng nhân quả. Cùng kỳ đó
> lượng ticket, cơ cấu vấn đề và các thay đổi khác đều có thể đã đổi.

**Designing against "−9.5 points means my fix worked":**

1. The delta never appears alone. Both denominators sit in the same cell:
   `82,1% (n=611) → 96,1% (n=930)`. A grown denominator is visible in the same
   glance as the delta.
2. **No arrow glyph and no green/red tone on the delta.** The ledger uses tone
   for state; this table deliberately does not, because tone reads as verdict.
   The delta renders in `--ink` with an explicit `điểm` unit.
3. The column header is `Chênh lệch trước–sau` — a difference — never "Tác
   động" or "Cải thiện". The nav label remains `Tác động thay đổi`, but the
   table's own column never claims impact.
4. When R3–R6 refuse, the delta cell shows **the reason**, not a blank and not
   an em dash. The reader learns why there is no number.

### C5 — Skill-name join

- Langfuse side: `metadata.skills_used` from the `execute` observation with the
  `customer-service/` prefix stripped (`enrichment.py:211`), yielding
  `interbank-fund-transfer`, `topup`, `withdraw`, `topup-withdraw`.
- cs-agent side: `plugin_name` + `usecase_name`.
- **Join key:** `usecase_name` against the segment label after identical
  normalization on both sides (NFC, casefold, strip), **and** `plugin_name` must
  equal `taxonomy.skills_prefix_strip.rstrip("/")` so a future second plugin
  cannot silently collide.
- **No fuzzy matching, ever.** Attaching a real change to the wrong skill's
  numbers is worse than showing nothing.
- A change event with no matching segment label is still recorded and still
  drawn as a marker — the change did happen — but its table row reads
  `"Chưa có ticket nào gắn skill này"`, and it is counted in
  `unmatched_event_count`.
- A segment label with no change event is normal and produces no marker.
- `interbank-fund-transfer` carries 96% of labelled volume and **its join is
  unverified**: `/api/skills` returns 401 and no cs-agent credential exists yet.
  Verifying it is Batch 3's stop-or-go criterion.

### C6 — User interface

**Placement.** A fourth entry in `SECTIONS` (`AppShell.tsx:25`), between
`segments` and `diagnostics`:

```
Báo cáo tuần · Xu hướng · So sánh segment · Tác động thay đổi ·
Chẩn đoán · Chất lượng dữ liệu · Ticket Explorer
```

This respects the inverted pyramid of SPEC-v2 §5.5 — it is a comparison, so it
belongs with the segment comparison, above diagnostics. The DOM node is
`<section id="skillImpact">`, rendered from `BelowFold.tsx` immediately after
the segments section so tab order follows visual order.

**Chart marker**, extending the `wtdMarker` precedent
(`BelowFold.tsx:177-197`, `stroke-dasharray: 3 3`):

- A `<line>` at the week's band centre spanning `y1={0}` to `y2={INNER_HEIGHT}`,
  drawn on **both** panels so volume and rate stay aligned.
- **Non-colour encoding:** `stroke-dasharray: 2 4` — a visibly different rhythm
  from `wtdMarker` — plus a small triangle anchored at the baseline, plus a
  numeric superscript when several markers exist. Shape, position and dash;
  never colour alone. Stroke is `--rule-strong`, deliberately not a status
  colour, so it reads as annotation rather than alarm.
- **Text alternative:** each `<line>` is `aria-hidden`; the information lives in
  the SVG `<desc>` already wired through `aria-describedby`, extended with a
  generated sentence — `"Có 2 mốc thay đổi skill: tuần 13/07 (withdraw), tuần
  20/07 (topup)."` — and a visible `<ol>` below the chart pairing each
  superscript with its skill and week. Screen-reader and sighted users receive
  identical facts.
- **No new click target.** `renderWeekTargets` (`BelowFold.tsx:202`) already
  owns week selection; a second interactive layer would break the 44×44 tap
  target at 390 px.

**Before/after table.** A semantic `<table>` inside `.tableScroll` with a sticky
first column, sorted through the existing `DataTableSortButton`.

| Skill | Ghi nhận đổi | Trước (n) | Sau (n) | Chênh lệch trước–sau | Trạng thái |
|---|---|---|---|---|---|

- Row grain is one change event, collapsed per R6.
- `Ghi nhận đổi` shows the **date only** (`13/07/2026`). A 15-minute-resolution
  timestamp would imply precision the synthesis does not have.
- The metric shown is AI-first rate, matching the segment table's primary
  metric.
- `Trạng thái` is the plain-language verdict: `Đủ điều kiện so sánh` /
  `Đã loại tuần chứa thay đổi` / `Chưa đủ tuần đủ` / `Độ phủ hai kỳ chênh nhau` /
  `Mẫu quá nhỏ`.
- Sorted by date descending, consistent with the Weekly Report's newest-first
  governance.
- **Not exported.** No copy or CSV control. The 14-column contract is untouched.

**Empty state** — the day-one state, and the expected state for several weeks
(E3, and 8 of 13 cohort weeks currently hold no data):

```
Chưa ghi nhận thay đổi skill nào.
Dashboard bắt đầu ghi nhận từ 07/08/2026. Mỗi lần nội dung skill trên cs-agent
đổi, mốc thời gian sẽ hiện ở đây và trên biểu đồ xu hướng. Thay đổi trước ngày
này không khôi phục được.
```

The final sentence is required. Without it, absent markers read as absent
changes.

**Degraded state** (cs-agent unreachable or unconfigured), sanitized — no raw
payload, no internal error code, no stack trace:

```
Chưa kết nối được nguồn thay đổi skill.
Phần này tạm dừng cập nhật. Các số khác trên trang không bị ảnh hưởng.
Mốc đã ghi nhận trước đó vẫn hiện.
```

Previously recorded events keep rendering — the changelog is on local disk and
stays valid; only new detection stops. The section header carries
`Cập nhật lần cuối: …` so staleness is visible.

### C7 — Configuration and secrets

Four new variables in `.env` (mode `0600`, added to the
`grep -o '^[A-Z_]*=' .env` inventory):

```
CS_AGENT_ENABLED=false
CS_AGENT_BASE_URL=
CS_AGENT_TOKEN=
CS_AGENT_CAS_COOKIE=
```

- **Fail-closed:** the poller starts only when `CS_AGENT_ENABLED` is exactly
  `"true"`, all three remaining variables are non-empty, and `CS_AGENT_BASE_URL`
  parses as `https://` with a host in a one-entry allowlist
  (`cs-agent.zalopay.vn`). Anything else → the poller never starts,
  `skill_timeline.status = "disabled"`, and the dashboard behaves as today.
- These four are read **outside** `load_environment()`, which raises
  `ConfigurationError` on missing required variables — an unset
  `CS_AGENT_TOKEN` must not stop the service from booting.
- No new dependency: a dedicated `httpx.Client` inside `skill_timeline.py`,
  separate from `LangfuseClient`.
- **On 401/403:** set `auth_state = "expired"`, **stop polling for 6 hours** (no
  retry storm against an SSO endpoint), emit `skill_timeline_auth_expired`
  carrying no token, header, or response body — matching the discipline already
  in `llm_client.py`. The payload reports `status: "auth_expired"` and the UI
  shows `"Cần cấp lại quyền truy cập nguồn thay đổi skill."` with no mention of
  tokens and no error code. Recovery is: update `.env`, restart the single
  worker.
- **Operational wart, stated plainly.** The token is a browser JWT and will
  expire. `/api/auth/login` is an SSO redirect, not a machine grant, so no
  refresh flow is available and rotation is manual. **Batch 3 must measure the
  token lifetime.** If it turns out to be roughly daily, this feature is not
  sustainable in its current form and the correct answer is a read-only service
  account from the cs-agent team — not a refresh mechanism built against SSO.

---

## Payload delta

Additive only, delivered in **two version bumps, one per batch that changes the
persisted shape**. A batch must never add a key while leaving the version
untouched — an unversioned shape change makes a stale snapshot on disk parse as
valid and fail deeper.

| Batch | Adds | `_STORAGE_VERSION` (`dashboard_schema.py:23`) |
|---|---|---|
| 4 | `views.<week_definition>.same_period` | 5 → **6** |
| 6 | top-level `skill_timeline` | 6 → **7** |

Per SPEC-v2 §4.1 an older snapshot is ignored and refreshed, never converted;
`load()` already returns `None` on mismatch, so each bump costs one cold refresh.

**Batch 4 — inside each view** (see Part B for the full block):

```jsonc
"views": { "mon_fri": { "weekly": [], "by_week": {}, "same_period": { } | null } }
```

`same_period` is registered in the per-view key set, not `_DASHBOARD_KEYS`.

**Batch 6 — top level.** `skill_timeline` is genuinely global: a skill change
happens once, independent of which cohort definition the reader has selected.
Only its `cohort_week` field is cohort-dependent, and it is resolved per view at
read time.

```jsonc
"skill_timeline": {
  "status": "disabled",          // disabled | active | unavailable | auth_expired
  "recording_since": null,       // ISO UTC or null
  "last_polled_at": null,        // ISO UTC or null
  "unmatched_event_count": 0,
  "events": [
    {
      "skill_label": "withdraw",
      "detected_on": "2026-08-07",     // date only, no time
      "cohort_week": "2026-08-03",     // Monday, ISO
      "change_kind": "content",        // content | guardrail | added | removed
      "matched": true
    }
  ]
}
```

**Never present:** digests, `plugin_name`, any `UsecaseForm` field, URLs,
tokens, or `skill_id` — an internal cs-agent identifier, excluded under the same
principle that bans `traceId`.

Backend registration, all in `dashboard_schema.py`:

- **Batch 4:** add `"same_period"` to the per-view key set validated at `:956`;
  `_view_payload` (`:390-391`) emits it. New `_validate_same_period()` enforcing
  exact keys, `_week_string` on `cohort_week` and every `by_week` key, a
  date-only regex on `cutoff_date`, `1 ≤ cutoff_weekday ≤ 7` consistent with
  `cutoff_date`, `weeks_used ≥ 2`, and the presence of the running week in
  `by_week`. `_DASHBOARD_KEYS` (`:71`) is **not** modified.
- **Batch 6:** add `"skill_timeline"` to `_DASHBOARD_KEYS` (`:71`). New
  `_validate_skill_timeline()` called from `_validate_dashboard` (`:941`),
  enforcing exact keys, the `status` enum, at most 500 events,
  `_week_string(cohort_week)`, a date-only regex on `detected_on`, and
  `_safe_string` plus `_is_safe_intent_label` on every `skill_label`.
- `_dashboard_payload` (`:378`) takes each new argument in its own batch,
  defaulting to `same_period: null` and the disabled timeline payload.

Frontend, `dashboard-schema.ts`: `SamePeriodSchema` joins the view schema in
Batch 4; `SkillTimelineSchema` joins `DashboardSnapshotSchema` (`:345`) in Batch
6. Both `.strict()`. `skill_label` reuses the existing `labelKey` regex
`^[a-z0-9_-]{1,64}$`, which all four observed labels satisfy, so the browser
re-enforces the boundary independently. A `superRefine` asserts every
`same_period.by_week` key also exists in that view's `by_week`, mirroring the
existing cross-field check at `:297-319`.

Unchanged: metric formulas, the four outcome definitions, `_SEGMENTS`, the
14-column Weekly Report, and every existing field.

---

## Implementation order

TDD, sequential, each batch independently shippable with the dashboard never
broken between batches.

| # | Batch | First RED test |
|---|---|---|
| **1** | Expose the Skill segment tab. Add `{key:"skill", label:"Skill"}` to `SEGMENT_DIMENSIONS` (`BelowFold.tsx:44`) plus the A3 coverage line. Type-checks for free — `skill` is already in `TicketFilterKey` and `SegmentsSchema`, and cross-filter to Ticket Explorer already works | `report-sections.test.tsx::test_segment_tabs_expose_skill_dimension` |
| **2** | Copy rewrite (Part A). No backend change | `narrative.test.ts::test_narrative_has_no_methodological_advice_strings` |
| **3** | cs-agent discovery. Throwaway probe, not product. Requires the PO to place a token in `.env` first. Nothing ships to the browser | `test_skill_timeline_client.py::test_client_is_disabled_without_configuration` |
| **4** | Same-period (Part B): `same_period` inside each view, **storage v5 → v6**, narrative, chart toggle | `test_pipeline.py::test_same_period_truncates_every_week_at_the_same_completed_day` |
| **5** | Store and poller (C1–C3), server-only, **payload byte-identical to Batch 4** | `test_skill_timeline_store.py::test_first_poll_records_digests_without_emitting_events` |
| **6** | `skill_timeline` payload, **storage v6 → v7**, with the privacy tests as the point of the batch | `test_dashboard_schema.py::test_skill_timeline_never_serializes_skill_body_text` |
| **7** | Before/after engine (C4), pure functions in `frontend/src/lib/skill-impact.ts`, no UI | `skill-impact.test.ts::test_the_week_containing_a_change_is_excluded_from_both_sides` |
| **8** | UI: markers, table, nav, empty and degraded states (C6) | `skill-impact-section.test.tsx::test_empty_state_states_history_is_not_recoverable` |

Batch 4 additionally requires
`test_same_period_is_null_on_monday_when_no_day_has_completed`,
`test_same_period_is_null_when_the_current_week_is_complete`,
`test_same_period_by_week_includes_the_running_truncated_week`,
`test_same_period_is_computed_independently_for_mon_fri_and_mon_sun`,
`test_same_period_baseline_skips_empty_weeks_rather_than_counting_them_as_zero`,
and a Zod test asserting a payload with `same_period` at top level is rejected.

Batch 5 additionally requires `test_store_ignores_and_backs_up_a_mismatched_schema_version`,
`test_backup_name_does_not_overwrite_an_existing_backup_of_the_same_version`,
`test_store_writes_0600_in_a_0700_directory`, and
`test_events_are_capped_at_500_and_400_days`.

Batch 6 additionally requires
`test_skill_timeline_rejects_a_label_that_is_not_a_safe_key` and
`test_skill_timeline_never_serializes_a_digest_or_skill_id`. Python and TS
fixtures regenerate in the same commit as the Zod schema.

Batch 7 requires one test per rule R1–R7. **The R4 test must use the real E3
figures (2026-06-29 through 2026-07-20) and assert the engine refuses the
comparison.**

Batch 8 updates `tests/test_frontend_contract.py` with the new DOM IDs
(`skillImpact`, `skillImpactTable`, `skillImpactEmpty`) in the same commit, per
SPEC-v2 §5.18.

### Batch 3 must produce written findings before Batch 5 begins

1. Does `usecase_name` for the interbank skill equal `interbank-fund-transfer`?
   **If it does not join, stop and re-plan** — the feature rests on this.
2. Digest stability across 3 polls over at least 2 minutes (the C2 gate).
3. Measured token lifetime — is manual rotation viable (the C7 wart)?
4. `GET /api/tickets/dashboard` and `GET /api/tickets/export`: both have untyped
   (`{}`) response schemas in the OpenAPI, so their shape cannot be known
   without an authenticated call. Fetch with a 7-day range and record the
   top-level shape, whether they carry outcome metrics overlapping this
   dashboard, and whether they contain PII. **Written decision only — replace,
   supplement, or ignore. No migration is designed here.** Prior expectation,
   given `/export` and the untyped schema: these are operational ticket exports
   containing raw customer data, therefore supplement at most and probably
   ignore. The finding must confirm or refute that.

### Scope boundary

`entry_point`, `tpe`, and `guardrail_rule` are **not** added as segment tabs.
`tpe` and `guardrail_rule` already appear in Transfer diagnostics with their
"overlapping indicators, not a partition" caveat; duplicating them as tabs would
create two differently-caveated views of one number. `entry_point` has no
product question attached. Five tabs, not eight.

---

## Files

| File | Work |
|---|---|
| `frontend/src/lib/narrative.ts` | A1 — drop `WTD_NOT_COMPARABLE`, consume `same_period` |
| `frontend/src/lib/selectors.ts` | A2 — rail keeps actionable items only (:329-400) |
| `frontend/src/components/DataQualitySection.tsx` | A4 — `coverageConsequence` (:27-43) |
| `frontend/src/components/BelowFold.tsx` | Batch 1 Skill tab (:44); Batch 4 chart toggle; Batch 8 markers (following `wtdMarker` :177-197) and the new section |
| `frontend/src/components/TransferDiagnostics.tsx` | A3 — Step result line |
| `frontend/src/components/AppShell.tsx` | Batch 8 — `SECTIONS` (:25) gains a fourth entry |
| `frontend/src/lib/skill-impact.ts` | **New** — R1–R7 engine |
| `frontend/src/lib/dashboard-schema.ts` | Zod for `same_period` and `skill_timeline` (:345) |
| `src/weekly_cs_report/skill_timeline.py` | **New** — client, canonical hashing, store, poller |
| `src/weekly_cs_report/pipeline.py` | Batch 4 — `same_period` aggregation |
| `src/weekly_cs_report/dashboard_schema.py` | `_STORAGE_VERSION` :23, `_DASHBOARD_KEYS` :71, `_dashboard_payload` :378, `_validate_dashboard` :941 |
| `src/weekly_cs_report/web.py` | `lifespan` :125 poller start/stop; configuration read |
| `DESIGN.md`, `docs/SPEC-v2.md` §5 | Fixed copy updated **in the same commit** |

---

## Verification

```bash
npm run test:unit && npm run typecheck && npm run build

# Deterministic Python suite — do not add dev dependencies to the shared .venv
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"

# PII boundary — all must be 0
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE '(0|84|\+84)[0-9]{8,10}'
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'content_digest|plugin_name|skill_id'

# permissions
stat -f "%Sp %N" .env runtime/dashboard_snapshot.json runtime/skill_changelog.json
# expect -rw------- on files and drwx------ on runtime/

grep -o '^[A-Z_]*=' .env        # names only, never values

# digest stability gate (Batch 3, required before Batch 5)
.venv/bin/weekly-cs-report skill-timeline-probe --repeat 3 --interval 60

npm run test:e2e   # axe, 1440x900 and 390x844, light and dark
```

UI verification uses Playwright and Chrome DevTools MCP at `1440×900` and
`390×844` in both themes: first viewport, global overflow, local table scroll,
sticky header and Tuần column, keyboard, focus, reduced motion, and 44×44 tap
targets. Measure with `evaluate_script` rather than judging from screenshots.
axe must report no serious or critical violations, and there must be no console
errors, CSP errors, or external network requests.

Release budget: initial JS ≤ 250 KB gzip, CSS ≤ 80 KB gzip. Current build is
136.55 kB and 5.06 kB; a table and a handful of `<line>` elements do not
threaten it.

**Reader verification.** For each rewritten string, read it as a CS colleague
who has never seen the pipeline. If there is nothing learned, the string is
deleted rather than reworded.

---

## Statements of record

1. **Part C cannot produce a valid comparison today, and likely will not for
   4–6 weeks.** E3 is decisive: skill coverage moved 0.33% → 84.6% across the
   only five weeks holding data, so every currently available cross-week skill
   comparison is confounded by instrumentation. Rule R4 makes the product refuse
   to show a delta, which is correct. The honest framing: **Batches 5–6 buy the
   recording that makes the analysis possible later; the analysis itself starts
   answering roughly four weeks after the poller goes live.** No engineering
   shortens this — the history does not exist and cannot be recovered.
2. **Realistically one skill will support a comparison** (E4). That skill is the
   bulk of traffic, so the feature remains worth building, but the UI must not
   imply otherwise.
3. **Manual JWT rotation may make Part C operationally unsustainable.** Batch 3
   measures it. A roughly daily lifetime means requesting a service account, not
   building a refresh mechanism against SSO.
4. **The join is unverified.** `interbank-fund-transfer` is 96% of labelled
   volume, `/api/skills` returns 401, and no credential exists. Batch 3 is the
   stop-or-go point.
5. **Do not backfill from `docs/skill/*/v*.json` mtimes** (E7).
6. **Parts A and B are fully independent of Part C.** If Part C is blocked at
   Batch 3, Batches 1, 2 and 4 still ship and still address the "cannot see
   movement" complaint at the running-week level.
7. **Reopen-reason labelling plugs in later** as one more before/after metric
   column in the Batch 8 table — the R1–R7 engine is metric-agnostic by
   construction. It must not be added before the §10 step-13 human gate clears.
