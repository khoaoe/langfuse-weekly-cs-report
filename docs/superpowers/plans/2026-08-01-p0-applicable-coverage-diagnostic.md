# P0 Applicable Coverage Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add actionable `entry_point`/TPE diagnostics to `verify-dimensions` without changing any legacy P0 count, rate, pass flag, exit code, or one-JSON stdout contract.

**Architecture:** Keep the raw all-ticket gate untouched. Classify normalized first traces into five mutually exclusive diagnostic populations (applicable, non-applicable, absent, null-string, invalid-type), add a sixth uninspectable population for raw units that could not normalize, and append privacy-validated aggregate fields to the existing report object.

**Tech Stack:** Python 3.11, pytest, existing `weekly_cs_report.dimension_verifier`, stdlib only.

## Global Constraints

- Authority: `docs/superpowers/specs/2026-08-01-p0-applicable-coverage-diagnostic-design.md`.
- Do not modify `_raw_dimension_present()`, thresholds `0.90`/`0.85`, raw denominator logic, or `p0_pass`.
- `coverage_tpe_applicable` must reuse the exact existing gate-local
  `tpe_present` boolean derived from trace metadata `Mã lỗi TPE`. Do not use
  dashboard `dimensions.tpe_signals`; that is a different observation source.
- `verify-dimensions` prints exactly one JSON object; no prose/stderr summary.
- No Freshdesk import/API/credential, runtime/dashboard artifact, payload, or
  dashboard change. Ignored mode-`0600` aggregate-only baseline evidence under
  `artifacts/p0_diagnostic_baseline/` is allowed; it contains no ticket ID/PII
  and is never committed or served.
- Preserve the dirty worktree. Do not reset, stash, overwrite, or commit without explicit user approval.

---

### Task 1: Lock the legacy baseline and classify entry-point source states

**Files:**
- Modify: `src/weekly_cs_report/dimension_verifier.py`
- Test: `tests/test_dimension_verifier.py`

**Interfaces:**
- Produces: `_diagnostic_entry_point(trace: TraceRecord, taxonomy: Taxonomy) -> tuple[str, str | None]`
- State values: `"absent"`, `"null_string"`, `"invalid_type"`, `"value"`.

- [ ] **Step 1: Capture the live legacy gate fields before editing**

Run with the same fixed window used by the spec and save only the
privacy-validated aggregate to an ignored private artifact with a stable path
that survives separate agent/shell steps:

```bash
mkdir -p artifacts/p0_diagnostic_baseline
chmod 700 artifacts/p0_diagnostic_baseline
.venv/bin/weekly-cs-report verify-dimensions --weeks 13 --include-current-wtd --as-of 2026-08-01T22:19:56+07:00 > artifacts/p0_diagnostic_baseline/before.json
chmod 600 artifacts/p0_diagnostic_baseline/before.json
.venv/bin/python -c 'import json,sys; json.load(open(sys.argv[1])); print("baseline-json-ok")' artifacts/p0_diagnostic_baseline/before.json
```

Expected: one valid JSON object. Keep this ignored aggregate until Task 3.

- [ ] **Step 2: Write RED tests for absent vs null-string vs real values**

Add cases that build synthetic traces with: missing `Thông tin thêm`, missing `sub_source`, `None`, `""`, `" null "`, `"None"`, `"undefined"`, `"tranxdetail"`, and `"resultpage"`.

```python
@pytest.mark.parametrize("value", ["", " null ", "None", "undefined"])
def test_diagnostic_entry_point_treats_null_like_values_as_broken(value):
    record = normalize_trace(_ticket_trace("t", "s", 0, "2026-07-21T01:00:00Z", entry_point=value))
    assert isinstance(record, TraceRecord)
    assert _verifier_module()._diagnostic_entry_point(record, load_taxonomy(TAXONOMY_V2)) == ("null_string", None)
```

Use a separate fixture mutation that keeps `sub_source` present with JSON
`null` (`None`) and assert `("invalid_type", None)`. Cover another non-string
value in the same state. Use another mutation that removes the key/container
and assert `("absent", None)`. Assert `" tranxdetail "` returns
`("value", "tranxdetail")`.

- [ ] **Step 3: Run the focused test and confirm RED**

```bash
uv run --isolated --extra dev --locked pytest -q tests/test_dimension_verifier.py -k diagnostic_entry_point
```

Expected: FAIL because `_diagnostic_entry_point` does not exist.

- [ ] **Step 4: Implement the minimal diagnostic-only classifier**

Add near `_raw_dimension_present()`:

```python
_NULL_LIKE_ENTRY_POINTS = frozenset({"", "null", "none", "undefined"})

def _diagnostic_entry_point(
    trace: TraceRecord,
    taxonomy: Taxonomy,
) -> tuple[str, str | None]:
    value: object = trace.input_data
    for key in ("other_info", "meta", *taxonomy.dimension_paths["entry_point"]):
        if not isinstance(value, Mapping) or key not in value:
            return "absent", None
        value = value[key]
    if not isinstance(value, str):
        return "invalid_type", None
    normalized = normalize("NFKC", value).strip()
    if normalized.casefold() in _NULL_LIKE_ENTRY_POINTS:
        return "null_string", None
    return "value", normalized
```

Do not call this helper from `_raw_dimension_present()`.

- [ ] **Step 5: Run focused tests GREEN**

```bash
uv run --isolated --extra dev --locked pytest -q tests/test_dimension_verifier.py -k diagnostic_entry_point
```

Expected: PASS.

---

### Task 2: Add mutually exclusive, privacy-bounded diagnostic aggregates

**Files:**
- Modify: `src/weekly_cs_report/dimension_verifier.py`
- Test: `tests/test_dimension_verifier.py`

**Interfaces:**
- Extends `aggregate_dimension_coverage()` return object with the exact keys in the spec.
- Preserves every pre-existing key and value.

- [ ] **Step 1: Write a RED aggregate test with all six populations**

Build six normalized sessions: `tranxdetail`, `resultpage`, absent, literal
`"null"`, JSON `null` (or another non-string), and one arbitrary valid string
containing a private marker. Add a seventh malformed raw unit which remains in
the raw denominator but cannot produce a normalized first trace. The arbitrary
valid string belongs to the same non-applicable population as `resultpage`;
the malformed raw unit alone is uninspectable. Assert:

```python
assert report["applicable_ticket_count"] == 1
assert report["non_applicable_ticket_count"] == 2
assert report["entry_point_absent_count"] == 1
assert report["entry_point_null_string_count"] == 1
assert report["entry_point_invalid_type_count"] == 1
assert report["diagnostic_uninspectable_ticket_count"] == 1
assert sum(report[key] for key in population_keys) == report["ticket_count"]
```

Also assert `category_gap_by_entry_point` uses only the fixed labels
`tranxdetail`, `resultpage`, `<absent>`, `<null-string>`, `<invalid-type>`,
`<other-valid>` and `<uninspectable>`; an arbitrary metadata value containing a
private marker must be counted under `<other-valid>` and must not appear in the
serialized report. Assert `coverage_tpe_applicable` uses only `tranxdetail`.
The `tranxdetail` fixture must carry `input.other_info.meta["Mã lỗi TPE"]` and
no observation/enrichment fixture; assert it increments
`applicable_tpe_present`. This locks the diagnostic to the existing P0
`tpe_present` semantic rather than dashboard `tpe_signals`.

In the same RED change, extend the existing CLI test to assert stderr is empty,
stdout has exactly one newline/JSON object, and the six population counts sum
to `ticket_count`.

- [ ] **Step 2: Confirm RED**

```bash
uv run --isolated --extra dev --locked pytest -q tests/test_dimension_verifier.py -k 'diagnostic_populations or applicable_diagnostics or verify_dimensions_cli'
```

Expected: FAIL on missing report keys.

- [ ] **Step 3: Implement counters inside the existing first-trace loop**

Initialize counters before the loop and update them after `issue_present` and `tpe_present` are computed. Use exact rules:

```python
state, entry_point = _diagnostic_entry_point(first_trace, taxonomy)
if state == "absent":
    entry_point_absent_count += 1
    gap_label = "<absent>"
elif state == "null_string":
    entry_point_null_string_count += 1
    gap_label = "<null-string>"
elif state == "invalid_type":
    entry_point_invalid_type_count += 1
    gap_label = "<invalid-type>"
elif entry_point == "tranxdetail":
    applicable_ticket_count += 1
    applicable_tpe_present += int(tpe_present)
    gap_label = entry_point
else:
    non_applicable_ticket_count += 1
    gap_label = entry_point if entry_point == "resultpage" else "<other-valid>"
if not issue_present:
    category_gap_by_entry_point[gap_label] += 1
```

In `verify_raw_ticket_dimensions()`, compute
`diagnostic_uninspectable_ticket_count` explicitly as raw denominator minus the
number of unique normalized session IDs, validate it is non-negative, and pass
it into `aggregate_dimension_coverage()`. Do not derive it implicitly from
`ticket_count_override` inside the aggregate.

After `ticket_count` is known:

```python
coverage_tpe_applicable = (
    applicable_tpe_present / applicable_ticket_count
    if applicable_ticket_count else 0.0
)
```

Return the exact fields from the spec. Treat `category_gap_by_entry_point` as an
unordered JSON object; the CLI already uses `sort_keys=True`, so serialized keys
are deterministic lexical order, not ranking order. Never serialize an
arbitrary raw `sub_source`. Do not derive any pass flag from diagnostics.

- [ ] **Step 4: Strengthen the legacy-isolation test**

Create a constant tuple of legacy keys and compare a fixture's expected legacy object exactly. Include `ticket_count`, both trace counts, both present counts, both coverage values, both pass flags, `p0_pass`, and `unmapped_tpe_codes`.

- [ ] **Step 5: Run targeted tests GREEN**

```bash
uv run --isolated --extra dev --locked pytest -q tests/test_dimension_verifier.py tests/test_deployment_contract.py tests/test_categories.py
```

Expected: all pass; retired Freshdesk applicability names remain absent.

---

### Task 3: Prove CLI/privacy compatibility and run the full gate

**Files:**
- Modify: `tests/test_dimension_verifier.py`
- Modify only if needed for documented output keys: `CLAUDE.md`

**Interfaces:**
- Consumes the extended report object.
- Produces no new command, output stream, artifact, or exit behavior.

- [ ] **Step 1: Re-run the CLI assertions added RED in Task 2**

```bash
uv run --isolated --extra dev --locked pytest -q tests/test_dimension_verifier.py -k verify_dimensions_cli
```

Expected: PASS with `captured.err == ""`, exactly one newline/JSON object, and
the six population counts summing to `ticket_count`.

- [ ] **Step 2: Run the full deterministic suite**

```bash
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

Expected: full Python suite PASS.

- [ ] **Step 3: Compare live legacy fields byte-for-value**

```bash
after_file="artifacts/p0_diagnostic_baseline/after.json"
.venv/bin/weekly-cs-report verify-dimensions --weeks 13 --include-current-wtd --as-of 2026-08-01T22:19:56+07:00 > "$after_file"
chmod 600 "$after_file"
.venv/bin/python - artifacts/p0_diagnostic_baseline/before.json "$after_file" <<'PY'
import json, sys
keys = (
    "ticket_count", "trace_issue_category_present_count",
    "trace_tpe_present_count", "issue_category_present_count",
    "tpe_present_count", "coverage_issue_category", "coverage_tpe",
    "p0_issue_category_pass", "p0_tpe_pass", "p0_pass",
)
before, after = (json.load(open(path)) for path in sys.argv[1:])
assert {k: before[k] for k in keys} == {k: after[k] for k in keys}
print("legacy-p0-identical")
PY
```

Expected: `legacy-p0-identical`. The live diagnostic counts may drift; do not
hard-code them. Keep both ignored aggregate files as review evidence; they
contain no ticket ID/PII and must remain mode `0600`.

- [ ] **Step 4: Review the scoped diff**

```bash
git diff --check -- src/weekly_cs_report/dimension_verifier.py tests/test_dimension_verifier.py CLAUDE.md
git diff -- src/weekly_cs_report/dimension_verifier.py tests/test_dimension_verifier.py CLAUDE.md
```

Expected: no whitespace errors; no change to gate formulas. Do not commit on the current dirty branch without user approval.
