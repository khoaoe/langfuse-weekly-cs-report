# Complete P4 Dashboard UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the SPEC-v2 P4 presentation layer without changing dashboard metrics, browser payloads, privacy boundaries, or Langfuse access.

**Architecture:** Keep the single inline HTML/CSS/JavaScript artifact required by the CSP contract. Add browser-observable behavior through the existing DOM helpers, use a measured sticky offset instead of viewport guesses, and make every selection visibly scoped. Extend the Node DOM harness only enough to exercise real event handlers and focus transitions.

**Tech Stack:** Semantic HTML, inline CSS, vanilla JavaScript, SVG, pytest, Node 24.

## Global Constraints

- Preserve the four outcome definitions and all deterministic metric formulas.
- Keep all style and script content inline; do not add external assets or chart libraries.
- Preserve same-origin API literals and the current CSP hash generation.
- Never serialize customer text, internal trace/session identifiers, or denied metadata into the browser.
- Use only the approved palette from SPEC-v2 §5.3 and one font family.
- Keep `.env` mode `0600`, `runtime/` mode `0700`, and the snapshot mode `0600`.
- Do not initialize Git and do not claim Docker verification.

---

### Task 1: Responsive shell and keyboard-safe sticky layout

**Files:**
- Modify: `tests/test_frontend_contract.py`
- Modify: `src/weekly_cs_report/static/index.html`

**Interfaces:**
- Consumes: existing `#sectionNav`, `.topbar`, `.weekly-table-scroll`, and `initialise()`.
- Produces: `syncStickyOffset(): void`, a visible skip link, measured `--sticky-offset`, and event behavior observable in the Node harness.

- [x] **Step 1: Write failing tests**

Add tests that require:

```python
assert 'id="skipToContent"' in page
assert 'id="dashboardMain"' in page
assert "function syncStickyOffset()" in page
assert "ResizeObserver" in page
assert "--sticky-offset:124px" not in page
assert "--sticky-offset:232px" not in page
```

Extend the harness so `addEventListener`, `dispatchEvent`, `focus`, `activeElement`, and `getBoundingClientRect` expose actual behavior, then dispatch the help and reset button handlers.

- [x] **Step 2: Run tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "sticky or help or reset"
```

Expected: failure because the current page has no skip target and uses fixed sticky offsets.

- [x] **Step 3: Implement the responsive shell**

Add a skip link targeting `<main id="dashboardMain">`. Implement:

```javascript
function syncStickyOffset(){
  const height=Math.ceil(document.querySelector(".topbar").getBoundingClientRect().height);
  document.documentElement.style.setProperty("--sticky-offset",`${height}px`);
}
```

Call it on initialization and from `ResizeObserver` when available. Keep a CSS fallback that is safe before JavaScript runs. Normalize controls to the 4px spacing scale, prevent form controls from widening the 390px viewport, and keep only local table/nav scrollers horizontally scrollable.

- [x] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "sticky or help or reset or responsive"
```

Expected: all selected tests pass.

---

### Task 2: Truthful scope, metric context, and warning semantics

**Files:**
- Modify: `tests/test_frontend_contract.py`
- Modify: `src/weekly_cs_report/static/index.html`

**Interfaces:**
- Consumes: `renderDashboard`, `renderKpis`, `renderWeeklyTable`, `updateFilters`, and `updated`.
- Produces: a headline scoped only to data actually rendered, Explorer-only segment chips, KPI definitions, freshness notes, and a reopen warning when the completed-week increase exceeds five points.

- [x] **Step 1: Write failing tests**

Add a scenario that applies a segment selection and asserts:

```javascript
{
  title: "Toàn kỳ · cohort T2–CN · 13 tuần · … ticket",
  chip: "Ticket Explorer · Nhóm vấn đề: …"
}
```

Add a completed-week scenario with reopen moving from `0.10` to `0.17`; assert the reopen card has class `attention` and explanatory text `Tăng trên 5 điểm`.

Add a weekly export scenario with two complete rows and assert every TSV data row has exactly 14 columns in the documented order.

- [x] **Step 2: Run tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "segment_scope or reopen_warning or weekly_export"
```

Expected: segment title is currently misleading and the warning class is missing.

- [x] **Step 3: Implement truthful context**

Keep the dynamic title scoped to active week plus selected week definition. Label segment chips as Explorer filters. Add `title` definitions to KPI cards and weekly column headers, append exact refresh time to KPI notes, and add a visible warning note/class only when the completed-week reopen delta is greater than five percentage points. Do not compare WTD.

- [x] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "segment_scope or reopen_warning or weekly_export or narrative"
```

Expected: all selected tests pass.

---

### Task 3: Aggregate long tails and finish diagnostic presentation

**Files:**
- Modify: `tests/test_frontend_contract.py`
- Modify: `src/weekly_cs_report/static/index.html`

**Interfaces:**
- Consumes: `renderSegments`, `renderDiagnostic`, `renderRules`, and the existing segment bucket shape `{total, ai_first, transferred, reopen}`.
- Produces: a real aggregate `Khác (N mục)` row, consistent diagnostic scope captions, and accessible tab/panel states.

- [x] **Step 1: Write failing tests**

Build 14 literal segment buckets. Assert the collapsed view contains one aggregate tail row whose total, AI rate, and transfer rate equal the hand-calculated sums, while the expanded view contains all 14 named rows and no duplicate aggregate.

Assert the rule and transfer panels expose period/cohort scope text and the selected segment tab keeps `aria-selected`, `tabindex`, and focus aligned after ArrowRight/Home/End.

- [x] **Step 2: Run tests and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "aggregate_tail or diagnostic_scope or keyboard"
```

Expected: the current “Khác” button has no aggregate metrics.

- [x] **Step 3: Implement aggregate and panel polish**

Sum all buckets after rank 12 into:

```javascript
{
  total: sum(total),
  ai_first: sum(ai_first),
  transferred: sum(transferred),
  reopen: sum(reopen)
}
```

Render it with the same bar/rate structure and a separate expand/collapse button. Add concise scope captions to the rule and transfer sections, without inventing new metrics.

- [x] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py -k "segment or diagnostic or keyboard"
```

Expected: all selected tests pass.

---

### Task 4: Full regression and live handoff

**Files:**
- Verify: `src/weekly_cs_report/static/index.html`
- Verify: `tests/test_frontend_contract.py`

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: a live P4 URL with passing repository checks and an explicit browser-QA evidence boundary.

- [x] **Step 1: Run frontend tests**

```bash
.venv/bin/pytest -q tests/test_frontend_contract.py
```

- [x] **Step 2: Run full repository verification**

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src tests
```

- [x] **Step 3: Verify live HTTP/security behavior**

Confirm `/`, `/readyz`, and `/api/dashboard` return `200`; `/docs`, `/redoc`, and `/openapi.json` return `404`; `no-store`, `nosniff`, CSP, and framing headers remain unchanged.

- [x] **Step 4: Verify runtime permissions**

Confirm `.env=0600`, `runtime/=0700`, and `runtime/dashboard_snapshot.json=0600`.

- [x] **Step 5: Record the browser limitation exactly**

If the supported browser runtime still has no backend, do not claim screenshot, overflow, console, computed contrast, or real keyboard traversal verification. Keep the service at `http://127.0.0.1:8765/` for user inspection and report the automated evidence separately.
