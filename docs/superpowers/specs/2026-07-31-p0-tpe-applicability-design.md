# SUPERSEDED — P0 TPE Applicability Design

**Date:** 2026-07-31
**Status:** **SUPERSEDED — DO NOT IMPLEMENT**
**Scope:** Historical record only

> This design is not an active metric or implementation contract. It was
> superseded on 2026-07-31 by
> [`2026-07-31-langfuse-only-p0-data-integrity-design.md`](2026-07-31-langfuse-only-p0-data-integrity-design.md).
> The active P0 gate is Langfuse-only, uses the full raw all-ticket denominator,
> and applies thresholds `0.90` for Issue Category and `0.85` for TPE. It does
> not use Freshdesk API data, a local backfill/overlay, or an applicability
> denominator. Everything below is preserved only to explain the retired
> approach and must not be executed or cited as current behavior.

## Root cause

The previous P0 gate divided TPE-present tickets by every root
`input.source == "ticket"` ticket. That denominator is not the source contract
for the field.

The internal Confluence page `[Ticket Freshdesk Dashboard] New Version`
(page `318769303`, version 22, updated 2026-06-17) defines:

- `custom_fields.cf_m_li_tpe` as `tpe_error`, “Mã lỗi từ TPE của giao dịch”;
- that field is present only when the ticket is submitted from the transaction
  flow;
- `custom_fields.cf_m_li` as the separate generic `error_code`, covering
  financial, transaction, or system errors.

The two Freshdesk fields must not be substituted for one another. A live
cross-field sample confirmed why: generic `cf_m_li` disagreed with the
specific TPE code on 12 of 371 tickets where the generic field existed.

Live Langfuse evidence for the fixed 12-week plus WTD window ending
`2026-07-31T10:00:00+07:00`:

- all root ticket sessions: `6,369`;
- all-ticket TPE present: `5,230` (`82.1165%`);
- independently identified transaction-detail tickets:
  `entry_point == "tranxdetail"`: `4,136`;
- TPE present in that applicable population: `4,136` (`100%`).

The real defect is therefore the P0 gate denominator, not a parser, taxonomy
mapping, cache, or hidden later-turn field.

## Source-contract boundary

This gate is a private Freshdesk/meta completeness check. It does not define
the dashboard TPE semantic:

- Dashboard `coverage.tpe`, Transstatus, and Step result come only from
  `tool:get_transaction_processing_engine_data` observations, as locked by
  `docs/SPEC-v2.md`.
- This verifier reads only the safe legacy `Mã lỗi TPE` code presence already
  retained for bounded private backfill/verifier use. It never interprets
  metadata `Step result`, status, case, or taxonomy meaning.
- The pre-existing verifier keys `tpe_present_count` and `coverage_tpe` remain
  for backward compatibility. In this command they are legacy private
  Freshdesk/meta presence measures, not the browser snapshot's
  observation-source `coverage.tpe`.
- Every new applicability key is namespaced `freshdesk_tpe` so release
  evidence cannot conflate the two contracts.

## Contract correction

Keep both measurements and name them explicitly:

1. `coverage_tpe` remains the all-ticket presence ratio. It is retained for
   transparency and compatibility and is not the release gate or dashboard
   Transstatus coverage.
2. `coverage_freshdesk_tpe_applicable` is the private Freshdesk/meta presence
   ratio within tickets whose canonical first trace has the configured
   transaction entry point `tranxdetail`. This is the P0 source-completeness
   gate.

The applicability contract is stored in taxonomy v2 as exactly:

```json
"applicable_entry_points": ["tranxdetail"]
```

The taxonomy loader rejects missing, duplicate, additional, or different
values. This prevents a configuration edit from silently gaming the
denominator.

The aggregate verifier additionally emits:

```text
freshdesk_tpe_applicable_ticket_count
freshdesk_tpe_applicable_present_count
freshdesk_tpe_applicable_missing_count
freshdesk_tpe_non_applicable_ticket_count
freshdesk_tpe_applicability_unknown_ticket_count
coverage_freshdesk_tpe_applicable
p0_issue_category_pass
p0_freshdesk_tpe_applicable_pass
p0_pass
```

The count invariant is:

```text
freshdesk_tpe_applicable_ticket_count
+ freshdesk_tpe_non_applicable_ticket_count
+ freshdesk_tpe_applicability_unknown_ticket_count
= ticket_count
```

Raw invalid or unkeyed ticket units, and normalized tickets whose entry point
is the taxonomy fallback, are applicability-unknown. They are never silently
discarded.

## P0 gate

- Issue category remains all-ticket:
  `coverage_issue_category >= 0.90`.
- Private Freshdesk/meta TPE completeness becomes applicability-aware:
  `freshdesk_tpe_applicable_ticket_count > 0` and
  `coverage_freshdesk_tpe_applicable >= 0.85`.
- `p0_pass` is true only when both conditions are true.
- An empty applicable population fails closed.

`verify-dimensions` continues to print one privacy-validated aggregate JSON
object. `--require-p0` makes the command return exit code `1` after printing
that object when `p0_pass` is false; the default diagnostic mode remains exit
code `0` for backward compatibility.

## Security and product boundaries

- Root ticket scope remains `input.source == "ticket"`.
- The all-ticket denominator and all-ticket TPE presence metric remain visible.
- No missing TPE is relabeled as present.
- The private gate is never described as dashboard Transstatus/Step result
  coverage.
- `cf_m_li` is not accepted as TPE.
- No observation dependency is added to the core P0 path.
- No ticket ID, trace ID, raw payload, credential, or Freshdesk value is added
  to verifier output.
- No runtime dependency, write API, deployment, or browser payload change is
  introduced.

## Acceptance

1. Taxonomy validation locks applicability to `tranxdetail`.
2. Unit tests prove the count invariant, canonical-first applicability despite
   conflicting later traces, empty-population fail-closed behavior, all-ticket
   compatibility, and P0 threshold boundaries.
3. CLI tests prove `--require-p0` returns `0` on pass and `1` on fail while
   printing only the safe aggregate object.
4. Full Python suite and compileall pass.
5. A fresh live run reports issue-category all-ticket coverage at least `0.90`
   and private Freshdesk/meta applicable TPE presence at least `0.85`.
6. Release evidence names the internal Confluence contract and separately
   reports all-ticket versus applicable TPE coverage.
