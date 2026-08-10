# SUPERSEDED — P0 TPE Applicability Implementation Plan

> **DO NOT EXECUTE THIS PLAN.** It was superseded on 2026-07-31 by
> [`../specs/2026-07-31-langfuse-only-p0-data-integrity-design.md`](../specs/2026-07-31-langfuse-only-p0-data-integrity-design.md).
> The active P0 contract is Langfuse-only, retains the full raw all-ticket
> denominator, and uses thresholds `0.90` / `0.85`; it has no Freshdesk API,
> local backfill/overlay, or applicability population. All unchecked tasks and
> pass expectations below are historical and void.

**Status:** **SUPERSEDED — HISTORICAL ONLY**

> **Historical worker instruction (void):** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real-data P0 gate use the source-backed TPE-applicable
population while preserving the all-ticket measurement and a fail-closed
machine gate.

**Architecture:** Extend taxonomy v2 with one exact transaction entry-point
contract, derive explicit applicability counts in the aggregate-only
dimension verifier, and add an opt-in nonzero CLI gate. Keep the dashboard
schema, runtime report pipeline, Freshdesk field extraction, and deployment
surface unchanged.

**Tech Stack:** Python 3.11 contract, standard library, pytest, existing
Langfuse/Freshdesk GET-only clients.

## Global Constraints

- Deployment, Docker execution, Kubernetes, ingress, PVC, secret rotation,
  push, and live rollout remain out of scope.
- Root ticket scope remains exactly `input.source == "ticket"`.
- Preserve the existing all-ticket fields `tpe_present_count` and
  `coverage_tpe`; never lower or round the all-ticket result.
- Treat those existing verifier fields as private legacy Freshdesk/meta
  presence only. Dashboard Transstatus/Step result and snapshot
  `coverage.tpe` remain observation-sourced under `docs/SPEC-v2.md`.
- Namespace every new applicability output with `freshdesk_tpe`; do not emit a
  new ambiguous `coverage_tpe_applicable` field.
- Never accept Freshdesk `custom_fields.cf_m_li` as a TPE source.
- Add no observation dependency to P0 and no runtime package.
- Add no identity, ticket ID, trace ID, raw payload, credential, URL, or raw
  Freshdesk field value to verifier output or logs.
- The P0 thresholds remain exactly issue category `0.90` and applicable TPE
  `0.85`; an empty applicable population fails closed.
- Taxonomy applicability must be exactly `["tranxdetail"]`; no arbitrary
  configurable denominator.
- Preserve user-owned dirty work. Do not stash, reset, clean, stage, commit,
  or edit outside each task's ownership.
- Follow RED -> verify expected failure -> GREEN -> refactor. Every code task
  ends with focused tests, compileall, and the complete Python suite.

---

### Task 1: Implement the source-backed P0 applicability gate

**Files:**

- Modify: `config/taxonomy.v2.json`
- Modify: `src/weekly_cs_report/categories.py`
- Modify: `src/weekly_cs_report/dimension_verifier.py`
- Modify: `src/weekly_cs_report/cli.py`
- Modify: `tests/test_categories.py`
- Modify: `tests/test_dimension_verifier.py`

**Interfaces:**

- Consumes: canonical first trace ordering `(turn, timestamp, id)`,
  taxonomy v2 `entry_point`, existing safe TPE parsing, raw ticket denominator.
- Produces: `Taxonomy.tpe_applicable_entry_points: tuple[str, ...]`, the nine
  `freshdesk_tpe` aggregate fields defined in the design spec, and CLI flag
  `--require-p0`.

- [ ] **Step 1: Write taxonomy RED tests**

  Add tests proving the checked-in taxonomy loads
  `tpe_applicable_entry_points == ("tranxdetail",)` and rejecting missing,
  empty, duplicate, extra, non-string, or different applicability values.

- [ ] **Step 2: Verify taxonomy RED**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_categories.py
  ```

  Expected: the new tests fail because taxonomy and `Taxonomy` do not expose
  `applicable_entry_points`.

- [ ] **Step 3: Implement the exact taxonomy contract**

  Add `"applicable_entry_points": ["tranxdetail"]` to the `tpe` object. Extend
  the v2 exact-key validator and `Taxonomy` dataclass. Reject every value except
  the exact one-element tuple `("tranxdetail",)`.

- [ ] **Step 4: Verify taxonomy GREEN**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_categories.py
  ```

  Expected: pass.

- [ ] **Step 5: Write aggregate-verifier RED tests**

  Extend the fixture helper with an explicit `entry_point`. Cover:

  - one `tranxdetail` ticket with TPE and one without;
  - explicit non-applicable entry point;
  - fallback/missing entry point;
  - a conflicting later-trace entry point that must not replace the canonical
    first trace;
  - raw invalid/unkeyed denominator units;
  - all-ticket `coverage_tpe` remaining unchanged;
  - applicable/non-applicable/unknown count reconciliation;
  - exact `0.90` and `0.85` boundaries;
  - empty applicable population producing
    `coverage_freshdesk_tpe_applicable == 0.0` and
    `p0_freshdesk_tpe_applicable_pass is False`.

- [ ] **Step 6: Verify aggregate RED**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_dimension_verifier.py
  ```

  Expected: fail because applicability and P0 fields do not exist.

- [ ] **Step 7: Implement minimal aggregate gate**

  In `aggregate_dimension_coverage`, derive applicability from the effective
  canonical trace's `entry_point`, while preserving the raw ticket override.
  Emit the nine exact fields from the design, enforce the count invariant, and
  compute:

  ```python
  p0_issue_category_pass = coverage_issue_category >= 0.90
  p0_freshdesk_tpe_applicable_pass = (
      freshdesk_tpe_applicable_ticket_count > 0
      and coverage_freshdesk_tpe_applicable >= 0.85
  )
  p0_pass = p0_issue_category_pass and p0_freshdesk_tpe_applicable_pass
  ```

  Keep `coverage_tpe` intact. Do not alter the current private legacy
  extractor or unmapped-code behavior; the current SPEC intentionally keeps
  dashboard TPE mapping disabled.

- [ ] **Step 8: Verify aggregate GREEN**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_dimension_verifier.py
  ```

  Expected: pass.

- [ ] **Step 9: Write CLI RED tests**

  Test `verify-dimensions --require-p0` after the subcommand:

  - a passing `tranxdetail` fixture prints one safe JSON object and returns `0`;
  - an applicable TPE miss prints one safe JSON object and returns `1`;
  - default diagnostic mode keeps returning `0` even when `p0_pass` is false;
  - parser state for existing commands remains unchanged.

- [ ] **Step 10: Verify CLI RED**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_dimension_verifier.py
  ```

  Expected: fail because `--require-p0` is unsupported.

- [ ] **Step 11: Implement CLI gate**

  Add the flag only to `verify-dimensions`. Reuse the already privacy-validated
  report; do not print a second line or error body. Return `1` only when the
  flag is present and `p0_pass is not True`.

- [ ] **Step 12: Verify Task 1**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_categories.py tests/test_dimension_verifier.py
  .venv/bin/python -m compileall -q src tests
  .venv/bin/pytest -q
  ```

  Expected: all pass with no warning/error output.

### Task 2: Align operating and release evidence

**Files:**

- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/SPEC-v2.md`
- Modify:
  `docs/superpowers/reports/2026-07-31-backend-production-readiness-report.md`

**Interfaces:**

- Consumes: the exact Task 1 output keys and verified live aggregate.
- Produces: reader-facing source contract, safe command, and current release
  verdicts.

- [ ] **Step 1: Update the source-of-truth contract**

  Amend SPEC-v2 P0, data-quality, and verification sections to state:

  - issue-category gate remains all-ticket;
  - private legacy TPE all-ticket presence remains visible and is explicitly
    different from dashboard observation-source `coverage.tpe`;
  - P0 private Freshdesk/meta completeness uses the exact `tranxdetail`
    applicability population and `freshdesk_tpe` names;
  - `cf_m_li` and `cf_m_li_tpe` are different fields and never substituted;
  - applicability counts must reconcile to the raw ticket denominator.

- [ ] **Step 2: Update operator documentation**

  Document `verify-dimensions --require-p0`, both coverage meanings, the fixed
  exit codes, and the internal Confluence source page. Do not add credentials
  to `.env` or command arguments.

- [ ] **Step 3: Record fresh live evidence**

  Run the exact 12-week plus WTD gate at
  `2026-07-31T10:00:00+07:00`. Record:

  - issue-category all-ticket counts/coverage;
  - TPE all-ticket counts/coverage;
  - private Freshdesk/meta TPE applicable counts/coverage;
  - backfill counts;
  - P0 verdict and remaining deployment-only blockers.

  Keep `backend_candidate=PASS`. Set `go_live=BLOCKED` because deployment gates
  remain deferred, not because P0 still fails.

- [ ] **Step 4: Verify Task 2**

  Run:

  ```bash
  .venv/bin/python -m compileall -q src tests
  uv run --isolated --extra dev --locked pytest -q
  .venv/bin/weekly-cs-report verify-dimensions --weeks 12 \
    --include-current-wtd --as-of 2026-07-31T10:00:00+07:00 --require-p0
  ```

  The runtime `.venv` intentionally contains production dependencies only;
  never install pytest into it. Expected: compile and the locked isolated full
  suite pass; live command returns `0`,
  `coverage_issue_category >= 0.90`,
  `coverage_freshdesk_tpe_applicable >= 0.85`, and `p0_pass: true`.

### Task 3: Independent final review

**Files:**

- Review only: every file owned by Tasks 1 and 2

**Interfaces:**

- Consumes: exact task-start snapshots, task reports, and fresh verification.
- Produces: dual verdict for spec compliance and code quality.

- [ ] **Step 1: Build exact before/after review package**

  Compare only files owned by this plan against their task-start snapshots;
  do not use the repository-wide dirty diff as task ownership evidence.

- [ ] **Step 2: Review critical risks**

  Confirm no denominator is hidden, legacy all-ticket TPE presence is
  preserved without being confused with dashboard observation coverage,
  applicability is locked to `tranxdetail`, empty applicability fails closed,
  CLI output is privacy-safe, and the report does not call deferred deployment
  complete.

- [ ] **Step 3: Run fresh final verification**

  Repeat Task 2 Step 4 and record exact output before any completion claim.
