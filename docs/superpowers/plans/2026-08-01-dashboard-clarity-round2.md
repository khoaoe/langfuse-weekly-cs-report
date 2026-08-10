# Dashboard Clarity Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the weekly CS dashboard readable to CS/PO users by removing misleading diagnostics, normalizing number presentation, adding readable chart interactions, and exposing the week filter.

**Architecture:** Frontend-only changes over the current React/Vite projection. Reuse current snapshot fields, preserve all metric formulas/payloads, and retain removed DOM IDs as hidden compatibility anchors for one release.

**Tech Stack:** React 19, TypeScript strict, Vitest/Testing Library, Visx/native SVG, CSS Modules, Playwright.

## Global Constraints

- Authority: `docs/superpowers/specs/2026-08-01-dashboard-clarity-round2-design.md`.
- No backend, payload, storage-version, metric, dependency, or legacy `static/index.html` change.
- Keep compatibility DOM IDs for one release as hidden, unfocusable anchors.
- Each task: RED → minimal implementation → GREEN → full frontend + Python gate.
- Preserve the pre-existing dirty worktree on branch
  `codex/zalopay-production-frontend`; no reset/stash/overwrite/commit without
  explicit approval. The path count is diagnostic, not a fixed requirement.

---

### Task 1: Remove the badge and replace the entire quality section atomically

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/DashboardScreen.tsx`
- Modify: `frontend/src/components/DataQualitySection.tsx`
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/src/components/TicketExplorer.tsx`
- Modify: `frontend/src/components/dashboard.module.css`
- Modify: `frontend/test/dashboard-screen.test.tsx`
- Modify: `frontend/test/coverage-branches.test.tsx`
- Modify: `frontend/test/report-sections.test.tsx`
- Modify: `frontend/test/data-table-sorting.test.tsx`
- Modify: `DESIGN.md`
- Modify: `docs/SPEC-v2.md`

**Interfaces:**
- Keep: `selectWeakestCoverage(snapshot)`.
- Remove from `AppShellProps`: `onOpenQuality`, `qualityExpanded`.
- Data-quality denominator: `snapshot.views.mon_sun.totals.eligible_ticket_count`; week count: `mon_sun.weekly.filter(row => row.has_data).length`.
- Remove `stepResultMissing` from `DataQualitySectionProps` and its caller.
- Keep only freshness, conditional weakest coverage, and empty-week explanation.

- [ ] **Step 1: Write RED render tests**

Assert no header button/element `#dqBadge`; assert the weakest line works for a
non-Skill weakest dimension as well as Skill, says recorded coverage,
consequence, and “không phải tỷ lệ ticket không được xử lý”; assert it uses
`mon_sun` totals even when active view fixtures differ. Add healthy coverage
case expecting only freshness + empty-week lines. Add absence assertions for
every literal listed in Part D of the spec; do not snapshot an entire page.

- [ ] **Step 2: Confirm RED**

```bash
npx vitest run frontend/test/dashboard-screen.test.tsx frontend/test/coverage-branches.test.tsx frontend/test/report-sections.test.tsx
```

Expected: failures on the old badge/copy.

- [ ] **Step 3: Implement the minimal UI change**

Delete `QualityBadge`, its props/call site, and badge-only CSS. In `DataQualitySection`, compute:

```tsx
const weakest = selectWeakestCoverage(snapshot);
const allTimeTickets = snapshot.views.mon_sun.totals.eligible_ticket_count;
const observedWeeks = snapshot.views.mon_sun.weekly.filter((row) => row.has_data).length;
```

Render the coverage paragraph only when `weakest !== null`, using
`formatRate(1 - weakest.missingShare)` for recorded share and
`formatRate(weakest.missingShare)` for the remainder plus the generic template
from the spec. Preserve `coveragePanel`; replace removed `qualityGrid`,
`gateGrid`, and `stepResultCoveragePanel` with empty `hidden aria-hidden="true"`
anchors. Delete `QUALITY_FIELDS`, the structural/gate/Step-result blocks, the
Intent hint, segment disclaimer, stale Survey sentence, and
`stepResultMissing` plumbing. Update `DESIGN.md` and `docs/SPEC-v2.md` so they
no longer require deleted visible copy and explicitly retain hidden-ID
compatibility for one release.

- [ ] **Step 4: Run GREEN and full gate**

```bash
npm run test:unit
npm run typecheck
npm run build
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"; uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

Expected: all pass.

---

### Task 2: Remove rule/guard panels without leaving an empty diagnostic state

**Files:**
- Modify: `frontend/src/components/TransferDiagnostics.tsx`
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/lib/selectors.ts`
- Modify: `frontend/src/lib/narrative.ts`
- Modify: `frontend/src/lib/ticket-columns.ts`
- Modify: `frontend/test/report-sections.test.tsx`
- Modify: `frontend/test/dashboard-screen.test.tsx`
- Modify: `frontend/test/ticket-columns.test.ts`

**Interfaces:**
- Remove from `TransferDiagnosticsProps`: `rule`, `onShowStuckTickets`.
- Keep `DashboardScreen.showStuckTickets` for the clickable KPI ledger.

- [ ] **Step 1: Write RED tests**

Assert the old explanatory text, `AlreadyCsZone`, the Guardrail table, and rule
button are not visible. Assert IDs `ruleGt4Panel`, `ruleScope`, `ruleGt4Alert`,
`escalationPanel` remain as hidden anchors without button role. Add a
blocked-only fixture and assert the normal empty state appears. Before deleting
the old rule button, assert clicking the ledger `>4 turn` cell still applies
`gt4_turn=true` plus `transferred=false` and opens Ticket Explorer. Assert the
old `Đã ở CS` column/filter label is replaced by `Chặn chuyển CS trùng` without
changing its key or values. Assert `guardrail_rule` is absent from the Explorer
column chooser/export allowlist, and rendered dashboard text contains none of
`Guardrail`, `missing_transaction_id`, `off_topic`, `cs_escalation`,
`rule đã bắn`, `guard chặn`, `khoảng trống rule`.

- [ ] **Step 2: Confirm RED**

```bash
npx vitest run frontend/test/report-sections.test.tsx frontend/test/dashboard-screen.test.tsx frontend/test/ticket-columns.test.ts
uv run --isolated --extra dev --locked pytest -q tests/test_frontend_contract.py
```

- [ ] **Step 3: Implement**

Delete visible rule facts/copy/button, the whole Guardrail distribution,
`AlreadyCsZone`, and the opening overlap paragraph. Retain the observation boundary through the title/labels
`Tín hiệu chuyển CS`; do not add causality wording or a replacement disclaimer.
Remove unused props and `BelowFold`'s derived `rule`. Change the empty-state
predicate so guardrail/escalation data alone does not count as visible content.
Add one hidden compatibility container with the four old IDs. Change only the
presentation label for the existing escalation field to `Chặn chuyển CS trùng`.
Remove `guardrail_rule` from the Explorer column allowlist without changing the
payload. Restrict narrative transfer signals to TPE and rewrite help/degraded
copy so no Guardrail/rule taxonomy is visible.

- [ ] **Step 4: Run full gate**

```bash
npm run test:unit && npm run typecheck && npm run build
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"; uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

Expected: all pass; the Python command remains unchanged legacy coverage and
must stay green without editing `static/index.html`, `static/legacy/index.html`
or `tests/test_frontend_contract.py`. KPI click-to-filter still passes.

---

### Task 3: Normalize KPI and segment-table number grammar

**Files:**
- Modify: `frontend/src/lib/selectors.ts`
- Modify: `frontend/src/components/DecisionLedger.tsx` only if markup needs count/support separation
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/test/decision-scope.test.tsx`
- Modify: `frontend/test/report-sections.test.tsx`

**Interfaces:**
- Every ledger `value` is a formatted count.
- `support` is a rate plus explicit denominator, or `null` for zero stuck tickets.
- Segment cells use `formatCount(count) + " · " + formatRate(rate)`.

- [ ] **Step 1: Write RED selector/table tests**

For a 935-ticket fixture, assert exact ledger values/support from the spec. For segment rows, assert Ticket, AI First, Chuyển CS, and Reopen all use the middle-dot grammar and no parenthesized share.

- [ ] **Step 2: Confirm RED**

```bash
npx vitest run frontend/test/decision-scope.test.tsx frontend/test/report-sections.test.tsx
```

- [ ] **Step 3: Implement selectors and cells**

Use count as `value`; calculate support with the exact scope fields:

```ts
value: formatCount(scope.aiFirstCount),
support:
  scope.eligible === 0
    ? null
    : `${formatRate(scope.aiFirstCount / scope.eligible)} trong ${formatCount(scope.eligible)} ticket tuần này`,
```

Use the same form for transfer and `>4 turn` with `scope.eligible`; reopen uses
`scope.reopenNumerator / scope.reopenDenominator` and says `ticket AI First`.
Guard every zero denominator and preserve `support: null` for `ledger-gt4` when
count is zero. Change segment header to `Ticket`, add the caption from the spec,
and use each bucket's own denominator for the three outcome columns.

- [ ] **Step 4: Run full gate**

```bash
npm run test:unit && npm run typecheck && npm run build
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"; uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

---

### Task 4: Add privacy-safe nice volume ticks

**Files:**
- Create: `frontend/src/lib/chart-scale.ts`
- Create: `frontend/test/chart-scale.test.ts`
- Modify: `frontend/src/components/BelowFold.tsx`

**Interfaces:**
- Produces: `niceVolumeTicks(maxVolume: number): readonly number[]`.
- Every result starts at zero, is ascending, uses a round step, and its final
  tick covers `maxVolume`.

- [ ] **Step 1: Write RED pure-function tests**

```ts
expect(niceVolumeTicks(1180)).toEqual([0, 250, 500, 750, 1000, 1250]);
expect(niceVolumeTicks(47)).toEqual([0, 10, 20, 30, 40, 50]);
expect(niceVolumeTicks(3)).toEqual([0, 1, 2, 3]);
expect(niceVolumeTicks(0)).toEqual([0, 1]);
```

Add invariant cases proving the final tick is never below a positive finite
input. Non-finite and negative input use the zero behavior.

- [ ] **Step 2: Confirm RED**

```bash
npx vitest run frontend/test/chart-scale.test.ts
```

- [ ] **Step 3: Implement the 1/2/2.5/5/10 × 10^n chooser**

Pick the smallest candidate that yields 4–5 intervals where possible; return
an immutable ascending array. Replace only the volume-axis `ticks()` path;
rate-axis ticks remain unchanged.

- [ ] **Step 4: Run full gate**

```bash
npm run test:unit && npm run typecheck && npm run build
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"; uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

---

### Task 5: Add accessible chart tooltips

**Files:**
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/src/components/dashboard.module.css`
- Modify: `frontend/test/trend-chart.test.tsx`

**Interfaces:**
- Reuses `.weekTarget`/`.weekHit` for pointer and existing `.weekSelector` for
  keyboard. Both feed one shared tooltip state; SVG targets stay `aria-hidden`
  and unfocusable.

- [ ] **Step 1: Write RED interaction tests**

Hover and focus a known week, assert exact volume/rate tooltip text; click still
selects the week; Escape/blur hides it. Assert tooltip node has no SVG `<title>`
dependency, has `role="tooltip"`, and the focused `.weekSelector` references it
through `aria-describedby`.

- [ ] **Step 2: Confirm RED**

```bash
npx vitest run frontend/test/trend-chart.test.tsx
```

- [ ] **Step 3: Implement one absolutely positioned tooltip**

Track one shared `{week, chart, anchorX}` state and derive text from the same row
rendered by the chart. Pointer handlers derive `anchorX` from the pointer event;
keyboard focus derives it from the focused `.weekSelector` button's
`getBoundingClientRect()` centre relative to the chart container. Clamp/flip
the tooltip near the right edge. Pointer handlers attach to existing SVG hit
areas; focus/blur/Escape attach to existing week buttons and write the same
state. Do not create another click overlay or make the `aria-hidden` SVG targets
focusable.

- [ ] **Step 4: Run full gate**

```bash
npm run test:unit && npm run typecheck && npm run build
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"; uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

---

### Task 6: Put the week filter first and fix Explorer alignment/captions

**Files:**
- Modify: `frontend/src/components/TicketExplorer.tsx`
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/src/components/dashboard.module.css`
- Modify: `frontend/test/data-table-sorting.test.tsx`
- Modify: `frontend/test/report-sections.test.tsx`
- Modify: `frontend/e2e/dashboard.spec.ts` or current equivalent returned by `rg --files frontend/e2e e2e`

**Interfaces:**
- Uses existing `filters.cohort_week` and `onFiltersChange` path; no new state key/API query parameter.
- Week options come from `view.weekly.filter(row => row.has_data)` newest first.

- [ ] **Step 1: Write RED Explorer tests**

Assert the first control in `#ticketFilters` is `Tuần`, blank option is `Tất cả tuần`, selecting a week updates the existing filter/chip/request, and Intent is still a `combobox` backed by `datalist`. Assert captions retain match counts but not “tăng dần/giảm dần”.

- [ ] **Step 2: Confirm RED**

```bash
npx vitest run frontend/test/data-table-sorting.test.tsx frontend/test/report-sections.test.tsx
npx playwright test frontend/e2e/dashboard.spec.ts --grep "Explorer week filter"
```

The Playwright test is RED before implementation and must cover both 390px and
1440px: week is the first filter, selecting it updates the active chip/request,
and Intent has the same rendered control height as peer fields.

- [ ] **Step 3: Implement using existing filter plumbing**

Render the week `<select>` first, map options with `formatWeekRange`, and call:

```tsx
update({ cohort_week: event.currentTarget.value })
```

Restore Intent to the same wrapping `<label>` structure as peer fields while retaining `<input list="intentOptions">`. Remove sort-direction prose from Explorer, segment, and TPE captions; do not remove `aria-sort` from headers.

- [ ] **Step 4: Run full automated gate**

```bash
npm run test:unit
npm run typecheck
npm run build
npm run test:e2e
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"; uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

- [ ] **Step 5: Browser acceptance at both viewports/themes**

Use the isolated Playwright server on `127.0.0.1:18765`. Verify 1440×900 and 390×844, light/dark, keyboard focus, no horizontal page overflow, 44px targets, equal filter-control heights, tooltip edge flipping, and that KPI/segment/filter cross-actions still work. Run axe and require zero serious/critical violations and zero console/CSP/external-network errors.

- [ ] **Step 6: Review the scoped diff**

```bash
git diff --check -- frontend DESIGN.md docs/SPEC-v2.md
git status --short
```

Expected: only task-owned edits plus pre-existing user changes; do not commit on the dirty branch without approval.

---

### Task 7: Product stress-test against every PO feedback group

**Files:**
- Test: existing focused Vitest/Playwright files from Tasks 1–6
- Modify only if a stress-test finds a real in-scope defect; add RED regression
  before any fix

- [ ] **Step 1: Build an A–F evidence matrix**

For each group, record at least one automated assertion and one browser check:
A scope, B jargon, C number grammar, D redundant copy, E chart ticks/tooltip,
F Explorer week/alignment/caption. No group may be marked complete from code
inspection alone.

- [ ] **Step 2: Run a global rendered-copy scan**

Across default, partial-data, empty-data and active-filter fixtures, assert no
visible internal phrases/raw codes from B and no deleted copy from D. Ensure
hidden compatibility anchors contain no text and are not focusable.

- [ ] **Step 3: Stress the real interaction chain**

At 1440×900 and 390×844, light/dark: select week in chart, switch to all-period,
drill from both clickable KPI cells, select/clear Explorer week, sort text and
numeric columns, hover/focus chart points, and collapse/expand long tables.
At every step verify displayed scope, active chips and counts refer to the same
population. Run axe and inspect console/network errors.

- [ ] **Step 4: Fix only evidenced regressions via RED→GREEN**

Any issue found gets a focused failing test first. Do not add speculative
features or change payload semantics. Repeat the complete gate after the final
fix.
