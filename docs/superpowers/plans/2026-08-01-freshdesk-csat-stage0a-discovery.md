# Freshdesk CSAT Stage 0A Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce privacy-safe evidence of the tenant's actual Freshdesk ticket, conversation, satisfaction-rating, agent, survey-scale, and response-identity contracts before any CSAT production pipeline is designed.

**Architecture:** A read-only discovery utility selects a bounded Langfuse ticket sample, probes Freshdesk in memory, and persists only field/type schemas plus aggregate candidate counts. It never writes raw responses or conversation/comment text. This plan ends at a mandatory PO/spec-review stop; Batches 1–6 deliberately have no implementation plan until this evidence exists.

**Tech Stack:** Python 3.11, existing `httpx`, existing Langfuse client/window code, pytest `MockTransport`, JSON artifacts with mode `0600`.

## Global Constraints

- Authority: `docs/superpowers/specs/2026-08-01-freshdesk-csat-integration-design.md`, Giai đoạn 0A only.
- Bulk satisfaction endpoint is permanently unavailable; do not probe/request/feature-flag it.
- Current `.env` is mode `0600` but exposes no `FRESHDESK_*`/`CSAT_*` variable names. The user must add `FRESHDESK_BASE_URL` and `FRESHDESK_API_KEY` directly to `.env`; never send values in chat or argv.
- GET only. No Freshdesk mutation, no raw payload on disk/stdout/log, no customer text, ticket list, agent name, or IDs in chat.
- Preserve the dirty worktree; no reset/stash/overwrite/commit without explicit approval.

---

### Task 0: Credential and repository preflight

**Files:**
- Read only: `.env`
- Read only: `AGENTS.md`, `CLAUDE.md`, `PRODUCT.md`

**Interfaces:**
- Requires environment names `FRESHDESK_BASE_URL`, `FRESHDESK_API_KEY`.
- Produces no artifact when either is absent.

- [ ] **Step 1: Verify names and permissions without reading values**

```bash
stat -f "%Sp %N" .env
grep -o '^[A-Z_]*=' .env | sed 's/=$//' | sort | grep '^FRESHDESK_'
```

Expected before continuing: `-rw------- .env` and exactly both required names. If absent, **STOP and ask the user to add them directly to `.env`**. Do not implement around missing credentials.

- [ ] **Step 2: Verify the dirty baseline**

```bash
git branch --show-current
git status --short
```

Record only branch name and path count. Never clean the worktree.

---

### Task 1: Build a bounded, non-serializing contract probe

**Files:**
- Create: `scripts/probe_freshdesk_csat_contract.py`
- Create: `tests/test_freshdesk_csat_contract_probe.py`
- Generate ignored: `artifacts/freshdesk_discovery/identity_checkpoint.json`

**Interfaces:**
- CLI: `python scripts/probe_freshdesk_csat_contract.py --schema-weeks 4 --schema-sample-size 50 --identity-weeks 13 --out artifacts/freshdesk_discovery/contract.json`
- Python: `run_contract_probe(ticket_ids: Sequence[str], settings: FreshdeskProbeSettings, *, transport: httpx.BaseTransport, out: Path) -> dict[str, object]`
- Settings: `load_probe_settings(env_path: Path) -> FreshdeskProbeSettings`,
  called only by this script's `main()`; importing the module performs no I/O.
- Produces: schema-only JSON described below.
- Must reject schema sample size `< 1` or `> 100`; default `50`. Identity scan
  is always exhaustive over `identity-weeks`, resumable, and has no sample cap.

- [ ] **Step 1: Write RED safety tests**

Use synthetic httpx responses containing obvious markers in ticket subject/body, conversation body, email, customer name, phone, feedback, API key, and IDs. Assert none of those values appear in stdout, stderr, exception text, or written JSON. Assert only GET requests target the configured HTTPS origin and redirects to another origin fail closed.

```python
def test_probe_persists_schema_not_values(tmp_path, monkeypatch):
    marker = "PRIVATE-MARKER-0901234567"
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/satisfaction_ratings"):
            payload = [{"agent_id": 42, "feedback": marker, "created_at": "2026-07-21T00:00:00Z"}]
        elif request.url.path.endswith("/conversations"):
            payload = [{"user_id": 42, "body_text": marker}]
        else:
            payload = {"subject": marker, "description": marker}
        return httpx.Response(200, json=payload)
    result = run_contract_probe(
        ticket_ids=("123",),
        settings=FreshdeskProbeSettings(
            base_url="https://support.example.test",
            api_key="test-secret",
        ),
        transport=httpx.MockTransport(handler),
        out=tmp_path / "contract.json",
    )
    serialized = json.dumps(result, ensure_ascii=False)
    assert marker not in serialized
    assert result["endpoints"]["satisfaction_ratings"]["shape"] == "list"
```

- [ ] **Step 2: Confirm RED**

```bash
uv run --isolated --extra dev --locked pytest -q tests/test_freshdesk_csat_contract_probe.py
```

Expected: FAIL because the probe module does not exist.

- [ ] **Step 3: Implement immutable schema summarization**

The probe may retain raw objects only in local variables. Convert each response immediately to a recursive field/type summary:

```python
def summarize_shape(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): summarize_shape(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return {"type": "list", "item_shapes": deduplicated_shapes(value)}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise ContractProbeError("unsupported response type")
```

Do not use `repr(value)` in errors. Add a value-shape validator before writing.
The artifact may contain endpoint names, HTTP status, field names, types,
nullability counts, array cardinality ranges, and aggregate collision counts
only. Field names such as `body_text` and `feedback` are allowed schema
evidence; their source values are forbidden.

Implement the dedicated loader with `dotenv_values(env_path)`: process
environment values override `.env`; select only the two exact Freshdesk names;
validate them; do not call `load_dotenv()` or mutate `os.environ`. Tests prove
importing the module does not open `.env`, and error text never contains either
credential value.

- [ ] **Step 4: Implement bounded GET surfaces**

For each of the 50 schema-sample tickets call only:

```text
GET /api/v2/tickets/{id}
GET /api/v2/tickets/{id}?include=stats
GET /api/v2/tickets/{id}/conversations?page=N&per_page=100
GET /api/v2/tickets/{id}/satisfaction_ratings
```

Use Basic auth, `Retry-After` capped at 300 seconds, max three retries, max 100 conversation pages, response-size cap 10 MiB, timeout 30 seconds, and concurrency 2. Do not follow cross-origin redirects. Reuse patterns from the sibling MCP by copying behavior, not importing it.

Separately, for **every ticket in the 13-week identity population**, call only
`GET /api/v2/tickets/{id}/satisfaction_ratings`. Do not fetch ticket/stats/
conversation for this exhaustive pass. Persist a private resumable checkpoint
after each week containing processed Ticket IDs, response-key hashes, missing
identity counts, and collision counts—never `agent_id`, feedback, label text or
raw response. A 30-minute max duration stops cleanly and the next identical
command resumes; the final contract is not marked complete until every ticket
in all 13 weeks has been checked.

Add MockTransport tests that interrupt after one week, assert
`identity_checkpoint.json` is mode `0600` and contains no forbidden raw fields,
then resume without requesting already processed ticket IDs. A changed window
or changed base-url host invalidates the checkpoint fail closed rather than
mixing populations.

- [ ] **Step 5: Write the artifact atomically with private permissions**

Create `artifacts/freshdesk_discovery/` mode `0700`; write a same-directory temp file mode `0600`, `fsync`, then `os.replace`. The final JSON contract is:

```json
{
  "schema_version": 1,
  "sample_size": 50,
  "identity_scan": {
    "weeks": 13,
    "completed": true,
    "ticket_count": 6663,
    "checked_ticket_count": 6663
  },
  "endpoints": {
    "ticket": {"status_counts": {}, "shape": {}},
    "ticket_with_stats": {"status_counts": {}, "shape": {}},
    "conversations": {"status_counts": {}, "shape": {}},
    "satisfaction_ratings": {"status_counts": {}, "shape": {}}
  },
  "identity_candidates": {
    "api_id_field_paths": [],
    "natural_key_fields": ["ticket_id", "survey_id", "agent_id", "created_at"],
    "missing_field_counts": {},
    "collision_count": 0
  },
  "survey_observations": [],
  "agent_field_candidates": []
}
```

Counts in the JSON example are illustrative schema values; live ticket counts
come from the selected Langfuse window and are never source constants.

`survey_observations` may contain only `survey_id`, rating numeric token, rating label token, and aggregate count after the privacy validator accepts each token. `agent_field_candidates` contains field paths/types only in 0A, not agent values/names.

- [ ] **Step 6: Run focused tests GREEN**

```bash
uv run --isolated --extra dev --locked pytest -q tests/test_freshdesk_csat_contract_probe.py
```

Expected: PASS.

---

### Task 2: Run the live probe and stop for contract review

**Files:**
- Generate: `artifacts/freshdesk_discovery/contract.json`
- Do not create yet: `config/freshdesk_agents.v1.json`

**Interfaces:**
- Consumes only credentials from process environment and sampled ticket IDs in memory.
- Produces aggregate/schema evidence only.

- [ ] **Step 1: Run the full Python baseline before network access**

```bash
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

Expected: PASS.

- [ ] **Step 2: Execute the bounded live probe**

```bash
uv run --isolated --locked python scripts/probe_freshdesk_csat_contract.py --schema-weeks 4 --schema-sample-size 50 --identity-weeks 13 --out artifacts/freshdesk_discovery/contract.json
stat -f "%Sp %N" artifacts/freshdesk_discovery artifacts/freshdesk_discovery/contract.json
```

If stdout reports `identity_scan_incomplete`, rerun the exact command until it
reports complete; this is expected with the 30-minute cap. Expected final:
directory `drwx------`, files `-rw-------`; stdout contains counts/status only.

- [ ] **Step 3: Run privacy and identity gates**

```bash
python - <<'PY'
import importlib.util
import sys
from pathlib import Path
script = Path("scripts/probe_freshdesk_csat_contract.py")
spec = importlib.util.spec_from_file_location("freshdesk_contract_probe", script)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
p = Path("artifacts/freshdesk_discovery/contract.json")
d = module.validate_contract_artifact(p)
assert d["identity_scan"]["completed"] is True
assert d["identity_scan"]["checked_ticket_count"] == d["identity_scan"]["ticket_count"]
assert d["identity_candidates"]["collision_count"] == 0
assert not d["identity_candidates"]["missing_field_counts"]
print("contract-gate-pass")
PY
```

`validate_contract_artifact()` rejects any leaf outside the documented
schema/type/count/safe-survey-token grammar. Expected: `contract-gate-pass`.
If the exhaustive identity scan is incomplete, or identity has no stable API ID
and the natural key has any collision/missing field, **STOP**.

- [ ] **Step 4: Mandatory handback — no Batch 0B or CSAT implementation**

Report only:

- endpoint status/shape verdict;
- whether ticket/stats can prove response participants;
- exact semantic candidate for `satisfaction_ratings.agent_id` or “unproven”;
- stable response-ID path, or natural-key collision result;
- survey IDs/rating tokens requiring PO mapping;
- which agent fields can support the next discovery step.

Do not paste agent IDs/names or raw values in chat. Request PO review of the private artifact. Only after that review may a new Stage 0B plan define `discover-agents`, `config/freshdesk_agents.v1.json`, and Batches 1–6.

- [ ] **Step 5: Review the scoped diff**

```bash
git diff --check -- scripts/probe_freshdesk_csat_contract.py tests/test_freshdesk_csat_contract_probe.py
git status --short
```

Expected: no whitespace errors; artifact remains ignored; no commit without user approval.
