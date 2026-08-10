# Langfuse-only P0 Data Integrity Design

**Date:** 2026-07-31 · **Revised:** 2026-08-01  
**Status:** User-mandated; authoritative over the earlier Freshdesk/backfill P0
design. **Revised 2026-08-01** to scope the rule to the P0 gate and core
metrics after the PO decided to add Freshdesk CSAT as a separate reported
metric.  
**Scope:** Reporting and release metrics only; deployment remains deferred

## Decision

**The P0 gate and every core metric must come from the configured Langfuse
project.** Freshdesk API responses, local Freshdesk-derived overlays, demo data,
fixtures, and manually supplied values must not affect P0 status, the four
outcomes, AI First, reopen, TPE distribution, or any segment.

The earlier private Freshdesk reconciliation path is retired from executable
reporting code. Historical documents may describe why it existed, but they are
not an active metric contract.

### Revision 2026-08-01 — what changed and what did not

The PO now requires customer-satisfaction data, which exists only in Freshdesk.
See `2026-08-01-freshdesk-csat-integration-design.md`. This revision states
exactly where the boundary now sits.

| Concern | Source | Changed by this revision |
|---|---|---|
| P0 gate (`verify-dimensions --require-p0`) | Langfuse only | **No. Permanent.** |
| Four outcomes, AI First, reopen, TPE, segments | Langfuse only | **No.** |
| CSAT (new) | Freshdesk | Yes — new read path |
| Outcome-mismatch diagnostic (new) | Freshdesk | Yes — **reports** a discrepancy; never rewrites a Langfuse number |

Binding conditions on the new Freshdesk path:

1. **P0 never reads Freshdesk.** No Freshdesk value may enter `p0_pass`,
   `coverage_issue_category`, or `coverage_tpe`. The gate keeps its raw
   all-ticket denominator exactly as specified below.
2. **The serving process never calls Freshdesk.** CSAT is fetched by a separate
   CLI into a cache; the dashboard process reads that cache. The statement
   "no server-side Freshdesk reads while serving a request" still holds.
3. **Every Freshdesk-derived number is labelled with its source on screen.**
   Mixing an unlabelled second source into a page of Langfuse numbers is the
   exact failure this document exists to prevent.
4. **Freshdesk never corrects a Langfuse metric.** A mismatch is shown as its
   own figure, next to the Langfuse figure, with both denominators stated.

`FRESHDESK_API_KEY` is read by the CSAT CLI only. The reporting and serving
paths still must not require it, and must start and run correctly without it.

## Authoritative source

P0 reads only root Langfuse traces returned by the allowlisted Public API
`GET /api/public/traces` path. A root ticket unit is one raw session where
`input.source == "ticket"`; direct chat is excluded only when
`input.source == "chat"`.

The verifier keeps the existing raw-denominator protection:

- valid sessions count once;
- malformed keyed sessions still remain in the denominator;
- unkeyed ticket units remain in the denominator;
- no source segment, entry point, category, or presence condition may narrow
  the denominator.

Dashboard observation metrics may continue to use the Langfuse Public API
`GET /api/public/observations`. They remain Langfuse-only and are separate from
this trace-metadata P0 gate.

## Exact P0 contract

The verifier emits these authoritative values:

```text
ticket_count
issue_category_present_count
tpe_present_count
coverage_issue_category
coverage_tpe
p0_issue_category_pass
p0_tpe_pass
p0_pass
```

Definitions:

```text
coverage_issue_category =
  issue_category_present_count / ticket_count

coverage_tpe =
  tpe_present_count / ticket_count

p0_issue_category_pass =
  ticket_count > 0 and coverage_issue_category >= 0.90

p0_tpe_pass =
  ticket_count > 0 and coverage_tpe >= 0.85

p0_pass =
  p0_issue_category_pass and p0_tpe_pass
```

All present counts are derived from the canonical first normalized Langfuse
trace only. The verifier must not read `runtime/dimension_backfill.json` or
another overlay. Missing values remain missing.

The retired fields below must not be emitted:

```text
issue_category_backfilled_count
tpe_backfilled_count
freshdesk_tpe_applicable_ticket_count
freshdesk_tpe_applicable_present_count
freshdesk_tpe_applicable_missing_count
freshdesk_tpe_non_applicable_ticket_count
freshdesk_tpe_applicability_unknown_ticket_count
coverage_freshdesk_tpe_applicable
p0_freshdesk_tpe_applicable_pass
```

The taxonomy must not contain a release-gate applicability population. In
particular, `entry_point == "tranxdetail"` may remain a dashboard dimension,
but it must not reduce the P0 denominator.

## Runtime removal boundary

- `verify-dimensions` reads Langfuse traces and taxonomy only.
- `compute_report` and `analyze_sessions` do not load or apply a local
  Freshdesk-derived overlay.
- The CLI does not expose `backfill-dimensions`.
- The P0 verifier, Langfuse report pipeline, dashboard serving process, dry-run,
  and refresh path do not require or read `FRESHDESK_API_KEY`. Under the
  Revision 2026-08-01 exception, only the dedicated `discover-agents` and
  `fetch-csat` CLI modules may read it lazily; they must not be imported by
  these Langfuse-only paths.
- The Freshdesk dimension client/store module is removed from the executable
  package.
- A pre-existing private cache is moved out of the active runtime directory
  into an ignored mode-0700 `.private-quarantine/` directory, recoverably; no
  production path recognizes the quarantined file.
- Freshdesk ticket links may remain as operator navigation. They are not a
  report data source and do not perform server-side Freshdesk reads.

## Current measured verdict

For the fixed 12-week plus WTD window ending
`2026-07-31T10:00:00+07:00`, the Langfuse-only read produced:

```text
ticket_count = 6369
issue_category_present_count = 5393
coverage_issue_category = 0.8467577327680955
tpe_present_count = 5045
coverage_tpe = 0.7921180719108181
p0_issue_category_pass = false
p0_tpe_pass = false
p0_pass = false
```

Therefore `p0_data=FAIL` and `go_live=BLOCKED`. A backend implementation
candidate may still pass code-quality gates, but it is not approved for
release.

## Anti-gaming invariants

1. Adding, editing, or deleting any ignored runtime backfill file cannot change
   verifier output, dashboard output, or CLI exit status.
2. Test fixtures and demo artifacts cannot be imported by production report
   code.
3. Live counts are never constants in executable source or configuration.
4. Thresholds remain exactly `0.90` and `0.85`.
5. `--require-p0` prints the same one privacy-validated JSON object and returns
   `1` whenever `p0_pass` is not exactly `true`.
6. Missing or empty ticket populations fail closed.
7. Documentation reports raw measured values even when they miss the target.

## Acceptance

1. Regression tests first demonstrate that the old overlay can change the
   current implementation, then pass only after every reporting path ignores
   it.
2. Parser tests prove `backfill-dimensions` is unavailable.
3. Source scans find no executable import or use of the retired backfill module
   or Freshdesk applicability gate. `FRESHDESK_API_KEY` may appear only in the
   dedicated CSAT CLI/client allowlist; call-graph/import tests prove P0,
   report, refresh and serving paths neither import that client nor read the
   variable.
4. Full Python and frontend verification, coverage gates, dependency audits,
   and wheel parity pass.
5. A fresh live `verify-dimensions --require-p0` run uses Langfuse only,
   reports the raw values above (or the newly observed raw values for the same
   fixed window), and exits `1`.
6. Independent review finds no Critical or Important data-integrity issue.
