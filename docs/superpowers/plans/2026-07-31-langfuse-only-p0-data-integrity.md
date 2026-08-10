# Langfuse-only P0 Data Integrity Implementation Plan

**Authoritative design:**
`docs/superpowers/specs/2026-07-31-langfuse-only-p0-data-integrity-design.md`

**Goal:** Make it mechanically impossible for Freshdesk data, a local overlay,
fixtures, or a narrowed denominator to turn raw Langfuse P0 from FAIL to PASS.

**Constraints:** Deployment, commit, push, secret rotation, and live rollout
remain deferred. Preserve unrelated user changes.

## Task 1 — RED contract tests

Modify verifier, pipeline, report, CLI, web, and deployment-contract tests to
prove:

- P0 uses all-ticket raw Langfuse issue-category and TPE presence;
- a local `runtime/dimension_backfill.json` cannot affect verifier or
  dashboard output;
- the `backfill-dimensions` command and Freshdesk credential path are absent;
- retired Freshdesk applicability keys are absent;
- exact thresholds are `0.90` and `0.85`;
- empty population fails closed;
- `--require-p0` returns `1` for the fixed raw-Fail shape.

Run the focused tests and record the expected RED failures before changing
production code.

## Task 2 — Remove Freshdesk reporting paths

- Delete the Freshdesk dimension client/store module.
- Remove overlay arguments/imports from verifier and pipeline.
- Remove runtime overlay loading from report and CLI.
- Remove `backfill-dimensions`, Freshdesk API-key handling, and related error
  catches from CLI.
- Remove active backfill-file handling from web startup.
- Remove `tpe.applicable_entry_points` from taxonomy and loader.
- Compute P0 from raw all-ticket counts only.

Run focused tests, compileall, and the full Python suite.

## Task 3 — Quarantine state and correct documentation

- Move the existing private backfill file out of active runtime into an
  ignored mode-0700 `.private-quarantine/` directory, retaining file mode
  `0600`.
- Update README, CLAUDE guidance, SPEC-v2, readiness design/report, and
  historical P0 design status.
- Publish the honest top-level verdicts:
  `backend_candidate`, `p0_data`, and `go_live`.
- Record raw Langfuse counts and explicitly state that no Freshdesk data was
  used.

Run source scans and `git diff --check`.

## Task 4 — Final verification and review

- Run isolated locked Python tests with total coverage at least 85% and named
  critical files at least 80%.
- Run frontend typecheck, unit coverage, build, and Playwright.
- Run dependency audits and current-source wheel parity.
- Run the fixed-window live Langfuse-only gate; expected exit is `1` while
  metrics remain below thresholds.
- Obtain independent spec, code, security, and data-integrity approval.
