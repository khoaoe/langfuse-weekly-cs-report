# Freshdesk CS-agent Entry Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bắt đầu từ toàn bộ ticket được tạo trên Freshdesk và chỉ ra riêng: ticket có bằng chứng CS-agent được gọi, ticket đã gọi nhưng không tạo phản hồi/chuyển CS, và ticket không thấy lần gọi CS-agent.

**Architecture:** Thêm một Freshdesk inventory job GET-only chạy ngoài serving process. Job liệt kê ticket Freshdesk theo thời gian tạo, đối chiếu Ticket ID với snapshot Langfuse hiện tại, chỉ đọc metadata conversation khi cần, rồi ghi một cache private chứa Ticket ID, thời gian và enum kết quả đã dẫn xuất. Snapshot v18 chỉ publish aggregate theo tuần; một API phân trang riêng cung cấp các ticket bất thường để điều tra. Không trộn Freshdesk-only ticket vào `Ticket Explorer`, không đổi công thức AI First/outcome/transfer hiện có. Inventory dùng `per_page=50` cố định và hai checkpoint private để resume từ 06/07/2026.

**Tech Stack:** Python 3.11 + stdlib/httpx hiện có, FastAPI, React 19, TypeScript strict, Zod 4, Vitest/Testing Library, Playwright, CSS Modules.

## Global Constraints

- Đây là **đối chiếu độ phủ đầu vào**, không phải survey và không thay đổi CSAT.
- Freshdesk là tập gốc: mọi ticket không spam/không deleted có `created_at` trong khoảng báo cáo đều được tính. V1 không gọi đây là “ticket đủ điều kiện”; wording là “ticket Freshdesk” vì chưa có contract chứng minh mọi source đều bắt buộc đi qua CS-agent. Probe ngày 2026-08-04 trên 100 dòng đầu quan sát source `{1: 14, 2: 50, 3: 31, 7: 2, 100: 3}`; không tự tạo source allowlist từ mẫu này.
- Hai trạng thái phải luôn tách riêng:
  - `invoked_no_result`: có ticket cùng ID trong Langfuse nhưng không có AI First và không có chuyển CS.
  - `not_observed_invoked`: không có ticket cùng ID trong Langfuse và không thấy public response của Admin CS ZaloPay trên Freshdesk.
- Không suy `not_observed_invoked` thành “CS-agent chắc chắn không được gọi”. Wording UI bắt buộc: **“Không thấy lần gọi CS-agent”**.
- Không dùng Freshdesk `is_escalated` để suy “AI chuyển CS”; field đó không chứng minh transfer của CS-agent. Chuyển CS vẫn lấy từ `TicketRow.transferred` của Langfuse.
- Public response của Admin CS ZaloPay được nhận diện bằng approved `bot_agent_ids`; CS người dùng approved `human_agent_ids`. Không phân loại bằng display name.
- Theo contract Freshdesk nội bộ, `category=3` là agent reply công khai; `category=1` là phía user, `category=2` là private note, `category=5` là system/automation và `category=7` là survey. Freshdesk conversations có thể trả body trong raw HTTP response, nhưng phải project ngay về bảy metadata tạm thời: ID để sort, author ID, incoming, private, source, category và created_at. Classifier dùng `category=3` cùng với `private=false`/`incoming=false` để nhận diện agent reply; không dùng `source != 6` làm điều kiện chính. Body, subject, requester, tên/email và attachment không được persist hoặc serialize.
- Cache/browser được phép có Ticket ID, `opened_at`, cohort week, enum trạng thái và boolean/nullable `human_replied`. Không được có agent ID/name, requester ID, group ID, raw/custom fields, conversation ID, text, URL, `traceId` hoặc `sessionId`.
- Serving process không gọi Freshdesk. Job ghi cache private `0600`; runtime directory giữ `0700`.
- Không thay đổi bốn outcome Langfuse, AI First, reopen, transfer, `gt4_turn`, weekly table 14 cột hoặc P0 gate.
- Global report scope áp dụng cho section mới. Ticket Explorer vẫn giữ local week override độc lập.
- Không đưa Freshdesk-only ticket vào `GET /api/tickets`: chúng không có outcome/Skill/Category Langfuse và việc điền placeholder sẽ làm sai nghĩa Ticket Explorer.
- Freshdesk List All Tickets là endpoint GET `/api/v2/tickets`; dùng `per_page=100`, `updated_since=<earliest-week-start UTC>`, `order_by=created_at`, `order_type=asc`, tối đa 300 trang theo [Freshdesk API](https://developers.freshdesk.com/api/). Lọc lại bằng `created_at` tại client; không request `include=requester|description|stats`.
- Bất kỳ lỗi trang, 429 hết retry, shape sai hoặc vượt page limit đều fail cả lượt publish; không công bố tuần một phần như dữ liệu hoàn chỉnh.
- Giữ dirty worktree. Không reset/stash/xoá/ghi đè thay đổi ngoài task và không commit nếu chưa có chỉ thị mới.

---

### Task 0: Re-verify source contract and baseline

**Files:**
- Read: `src/weekly_cs_report/dashboard_schema.py`
- Read: `src/weekly_cs_report/freshdesk_csat.py`
- Read: `src/weekly_cs_report/web.py`
- Read: `runtime/dashboard_snapshot.json`

**Produces:** Baseline xác nhận storage v16 trước implementation; sau implementation
storage là v18. List All Tickets dùng được; response không cần
requester/description; current snapshot có Langfuse Ticket IDs để join.

- [x] Ghi baseline không thay đổi worktree:

```bash
git branch --show-current
git status --short
rg -n '^_STORAGE_VERSION' src/weekly_cs_report/dashboard_schema.py
stat -f "%Sp %N" .env runtime runtime/dashboard_snapshot.json
```

Baseline trước phần triển khai cũ: `_STORAGE_VERSION = 16`; implementation cũ
publish v17. Phần resilience bổ sung publish v18 và chỉ nhận nguồn từ
`2026-07-06`.
`.env`/snapshot and private caches are `0600`, runtime is `0700`.

- [x] Chạy một live read-only probe giới hạn một trang qua client GET-only hiện có và chỉ in aggregate/shape:

```bash
uv run --isolated --locked python - <<'PY'
from datetime import datetime, timezone
from collections import Counter
from weekly_cs_report.cli import _freshdesk_settings
from weekly_cs_report.freshdesk_csat import FreshdeskClient

with FreshdeskClient(_freshdesk_settings()) as client:
    rows = client._get_json(
        "/api/v2/tickets",
        params={
            "updated_since": datetime(2026, 8, 2, 17, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "order_by": "created_at",
            "order_type": "asc",
            "page": 1,
            "per_page": 100,
        },
    )
valid = isinstance(rows, list) and all(
    isinstance(row, dict)
    and isinstance(row.get("id"), int)
    and isinstance(row.get("created_at"), str)
    and isinstance(row.get("source"), int)
    for row in rows
)
print({
    "status": "ok" if valid else "invalid_shape",
    "ticket_count": len(rows) if isinstance(rows, list) else 0,
    "source_counts": dict(sorted(Counter(row.get("source") for row in rows if isinstance(row, dict)).items())) if isinstance(rows, list) else {},
})
PY
```

Expected output chỉ có `status`, `ticket_count` và aggregate `source_counts`; không có Ticket ID hoặc giá trị field. Nếu endpoint trả 401/403 hoặc shape thiếu `id/created_at/source`, dừng trước Task 1. Source chỉ là diagnostic mẫu số, không được dùng làm filter nếu chưa có product contract mới.

- [x] Chạy baseline:

```bash
npm run test:unit
npm run typecheck
npm run build
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

---

### Task 1: Add strict Freshdesk entry-coverage cache and classifier

**Files:**
- Create: `src/weekly_cs_report/entry_coverage_cache.py`
- Create: `src/weekly_cs_report/freshdesk_entry_coverage.py`
- Modify: `src/weekly_cs_report/freshdesk_csat.py`
- Test: `tests/test_entry_coverage_cache.py`
- Test: `tests/test_freshdesk_entry_coverage.py`

**Interfaces:**

```python
EntryCoverageStatus = Literal[
    "ai_replied_only",
    "ai_replied_then_transferred",
    "transferred_without_ai_reply",
    "invoked_no_result",
    "not_observed_invoked",
    "unresolved",
]

@dataclass(frozen=True)
class EntryCoverageRecord:
    ticket_id: str
    opened_at: str                 # UTC ISO
    cohort_week: str               # Monday YYYY-MM-DD
    status: str
    human_replied: bool | None

@dataclass(frozen=True)
class EntryCoverageCache:
    fetched_weeks: Mapping[str, str]
    records: tuple[EntryCoverageRecord, ...]

@dataclass(frozen=True)
class FreshdeskTicketMetadata:
    ticket_id: str
    created_at: str                # UTC ISO

def classify_entry_coverage(
    ticket: FreshdeskTicketMetadata,
    langfuse_ticket: TicketRow | None,
    conversations: tuple[ConversationMetadata, ...],
    agents: ReconciliationAgentConfig,
) -> EntryCoverageRecord: ...
```

`entry_coverage_cache.json` schema v1 has exact top-level keys `schema_version`, `fetched_weeks`, `records`; exact record keys match the dataclass. Writer follows `reconciliation_cache.py`: atomic replace, no symlink, owner-only regular file, mode `0600`, duplicate Ticket ID rejected.

`FreshdeskClient` gains:

```python
def list_ticket_metadata(
    self,
    *,
    updated_since: datetime,
    max_pages: int = 300,
) -> tuple[FreshdeskTicketMetadata, ...]: ...
```

Projection at the network boundary keeps only `id` and `created_at`. Default Freshdesk behavior excludes spam/deleted; do not read subject, description, requester, custom fields or responder assignment.

- [x] RED tests for cache exact keys, invalid timestamps/statuses, duplicate IDs, symlink/permissive mode, atomic round-trip and schema mismatch.
- [x] RED table tests for classifier:

| Langfuse row | Freshdesk conversation evidence | Expected status | `human_replied` |
|---|---|---|---|
| `ai_first=true`, `transferred=false` | any valid metadata | `ai_replied_only` | `null` |
| `ai_first=true`, `transferred=true` | any valid metadata | `ai_replied_then_transferred` | `null` |
| `ai_first=false`, `transferred=true` | no bot reply | `transferred_without_ai_reply` | `null` |
| matched, both false | no bot reply, known human public outgoing | `invoked_no_result` | `true` |
| matched, both false | no public outgoing | `invoked_no_result` | `false` |
| unmatched | known human public outgoing only | `not_observed_invoked` | `true` |
| unmatched | no public outgoing | `not_observed_invoked` | `false` |
| unmatched | public bot outgoing exists | `unresolved` | `null` |
| unmatched | public outgoing author missing/not approved | `unresolved` | `null` |

Private notes, category `1`/`2`/`5`/`7`, incoming requester messages and source `6` never count as bot/human replies. Known excluded service IDs do not count and do not force unresolved. For a matched `invoked_no_result` ticket, an unknown public outgoing author keeps the status but makes `human_replied=null`; it must not be relabelled as `not_observed_invoked`.

- [x] GREEN implementation. Fetch conversations only for unmatched tickets and matched tickets where `ai_first=false && transferred=false`; this bounds API calls. Any transport/shape error aborts publish rather than creating `unresolved`.
- [x] Run:

```bash
uv run --isolated --extra dev --locked pytest -q \
  tests/test_entry_coverage_cache.py tests/test_freshdesk_entry_coverage.py
```

---

### Task 2: Add incremental CLI job and refresh orchestration

**Files:**
- Modify: `src/weekly_cs_report/cli.py`
- Modify: `src/weekly_cs_report/web.py`
- Modify: `scripts/refresh_dashboard_data.sh`
- Test: `tests/test_cli.py`
- Test: `tests/test_web.py`

**Interfaces:**

```bash
weekly-cs-report fetch-freshdesk-entry-coverage \
  --weeks 13 --max-workers 1 --max-duration 7200 \
  --runtime-dir /absolute/path/runtime
```

Success output contains aggregates only:

Example shape only:

```json
{
  "status": "complete",
  "weeks_fetched": 13,
  "freshdesk_ticket_count": 0,
  "invoked_no_result_count": 0,
  "not_observed_invoked_count": 0,
  "unresolved_count": 0
}
```

- [x] RED CLI tests: absolute safe runtime required; uses current protected snapshot for Langfuse join; missing approved bot/human roster fails sanitized; checkpoint resumes; incomplete run does not replace published cache.
- [x] Implement `fetch-freshdesk-entry-coverage`. Determine the date interval from the last `--weeks` rows of `views.mon_sun.weekly`. Convert Freshdesk `created_at` to Vietnam time for cohort Monday and weekend flag. Re-fetch current week plus the preceding 14 calendar days; retain older complete cached weeks.
- [x] Add `entry_coverage_cache.json` to `_validated_runtime_directory` allowlist, load it during snapshot refresh, and keep invalid-cache behavior fail-soft exactly like CSAT/reconciliation.
- [x] Insert the new job before CSAT in `scripts/refresh_dashboard_data.sh`; if it is not `complete`, cancel dashboard refresh and retain the last-good snapshot.
- [x] Run focused CLI/web tests, then full Python suite.

---

### Task 3: Publish storage/browser v18 aggregates and paginated drill-down

**Files:**
- Modify: `src/weekly_cs_report/dashboard_schema.py`
- Modify: `src/weekly_cs_report/dashboard_cache.py`
- Modify: `src/weekly_cs_report/web.py`
- Modify: `tests/test_dashboard_schema.py`
- Modify: `tests/test_dashboard_cache.py`
- Modify: `tests/test_web.py`
- Modify: `frontend/src/lib/dashboard-schema.ts`
- Modify: `frontend/test/dashboard-schema.test.ts`
- Modify: frontend fixtures that copy strict `DashboardView`

**Interfaces:**

Each view gains nullable `entry_coverage`:

```json
{
  "source": "freshdesk",
  "fetched_at": "UTC ISO",
  "by_week": {
    "2026-08-03": {
      "freshdesk_ticket_count": 161,
      "ai_replied_only": 98,
      "ai_replied_then_transferred": 36,
      "transferred_without_ai_reply": 0,
      "invoked_no_result": 5,
      "not_observed_invoked": 20,
      "not_observed_human_replied": 14,
      "not_observed_no_human_reply": 6,
      "unresolved": 2
    }
  }
}
```

Required invariants:

```text
freshdesk_ticket_count
= ai_replied_only
+ ai_replied_then_transferred
+ transferred_without_ai_reply
+ invoked_no_result
+ not_observed_invoked
+ unresolved

not_observed_invoked
= not_observed_human_replied
+ not_observed_no_human_reply
```

`DashboardSnapshot` gains a private/storage-only tuple `entry_coverage_tickets`. `_STORAGE_VERSION` becomes `18` in the same task. Each view also declares `source_start_week: "2026-07-06"`. `GET /api/dashboard` returns only aggregates.

New same-auth-boundary endpoint:

```text
GET /api/freshdesk-entry-coverage/tickets
  ?week_definition=mon_fri|mon_sun
  &cohort_weeks=2026-07-27,2026-08-03
  &status=not_observed_invoked
  &page=1&page_size=10
  &sort_by=opened_at&sort_dir=desc
```

Response:

```json
{
  "items": [{
    "ticket_id": "7043723",
    "opened_at": "UTC ISO",
    "cohort_week": "2026-08-03",
    "status": "not_observed_invoked",
    "human_replied": true
  }],
  "page": 1,
  "page_size": 10,
  "total": 1
}
```

- [x] RED strict-schema tests for every invariant, unknown key/status, week outside view and mon_fri weekend exclusion.
- [x] RED API tests for pagination, multi-week filter, status filter, sort, auth, malformed inputs and PII absence.
- [x] Implement projection and route atomically in Python + Zod. Do not add the new rows to existing `tickets` or `/api/tickets`.
- [x] Verify storage v17 is rejected rather than silently migrated; cache v1 remains independent of storage v18.

---

### Task 4: Add the CS-facing Freshdesk coverage section

**Files:**
- Create: `frontend/src/components/EntryCoverageSection.tsx`
- Create: `frontend/src/lib/entry-coverage.ts`
- Modify: `frontend/src/components/BelowFold.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/dashboard.module.css`
- Test: `frontend/test/report-sections.test.tsx`
- Test: `frontend/e2e/dashboard.spec.ts` or the existing main dashboard E2E file

**UI contract:**

- Place immediately after `Báo cáo tuần`, before `Volume và tỷ lệ theo tuần`.
- Section title: **“Độ phủ xử lý từ Freshdesk”**.
- One compact flow/table, not a card mosaic:
  - `Ticket Freshdesk`
  - `AI đã phản hồi`
  - `AI phản hồi rồi chuyển CS`
  - `Chuyển CS không có AI First`
  - `Đã gọi nhưng không có phản hồi/chuyển CS`
  - `Không thấy lần gọi CS-agent`
  - `Chưa xác định`
- Under `Không thấy lần gọi CS-agent`, show two exact subcounts: `CS người đã phản hồi trực tiếp` and `Chưa thấy CS người phản hồi`.
- Count leads; percentage is support text with `freshdesk_ticket_count` as denominator. Do not show rate when denominator is zero.
- Clicking one of the three investigation states (`invoked_no_result`, `not_observed_invoked`, `unresolved`) opens an inline detail table backed by the new endpoint. It does not change global scope or Ticket Explorer filters.
- Detail columns: `Ticket`, `Thời gian tạo`, `Trạng thái`, `CS người phản hồi trực tiếp`. Ticket link reuses the existing safe Freshdesk URL helper. Page size fixed at 10 with Previous/Next controls; sort newest/oldest.
- Empty state: `Không có ticket trong trạng thái này ở phạm vi đang chọn.`
- Unavailable cache state: `Chưa có dữ liệu đối chiếu từ Freshdesk.`
- Navigation label in `AppShell`: `Độ phủ Freshdesk` targeting `#entry-coverage`.

- [x] RED component tests for latest week, selected multiple weeks, all-period, mon_fri weekend exclusion, unavailable state, zero state, selection, pagination and no duplicate week control.
- [x] Implement with accessible table/button semantics. Status affordance uses normal text plus a compact `Xem ticket` button; no blue underlined value links.
- [x] E2E at 1440×900 and 390×844: no overflow, keyboard activation works, correct API query follows global scope, Ticket Explorer local override remains unchanged.

---

### Task 5: Documentation, privacy and delivery gates

**Files:**
- Modify: `PRODUCT.md`
- Modify: `DESIGN.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `.gitignore` only if the new private cache/checkpoint is not already covered

- [x] Document the factual boundary: `Không thấy lần gọi` means no Langfuse ticket and no approved bot public response; it is not proof of a failed trigger.
- [x] Document why Freshdesk-only tickets have a separate drill-down and are absent from Ticket Explorer.
- [x] Update setup/refresh sequence and cache filenames; do not add env vars because existing `FRESHDESK_BASE_URL` and `FRESHDESK_API_KEY` are sufficient.
- [x] Resilience update: inventory starts at `per_page=50`, resumes from
`inventory_checkpoint.json`, coverage resumes from
`coverage_checkpoint.json`, and neither checkpoint can replace the published
runtime cache. The browser payload declares `source_start_week=2026-07-06` and
uses storage schema v18.
- [x] Run full gates:

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

- [ ] Start the local dashboard, refresh all Freshdesk caches, and verify:

```bash
./scripts/refresh_dashboard_data.sh
curl -s http://127.0.0.1:8765/api/dashboard \
  | grep -cE 'UserID|TransID|traceId|sessionId|requester_id|agent_id|group_id'
stat -f "%Sp %N" .env runtime runtime/entry_coverage_cache.json runtime/dashboard_snapshot.json
```

Expected: blocked-field count `0`; `.env`, caches and snapshot `0600`; runtime `0700`.

Implementation evidence for the resilience change is covered by the focused
checkpoint, pagination, fixed-start and atomic-publish tests. A live full
Freshdesk refresh remains a separate operational run; this implementation does
not claim that network-dependent gate as completed.

- [x] Live acceptance check with safe aggregates only:
  - Every visible week satisfies both reconciliation equations.
  - `invoked_no_result` and `not_observed_invoked` are separate in API, UI and drill-down.
  - At least one status click opens the correct Freshdesk ticket list.
  - Changing Ticket Explorer week does not change this section; changing global report scope does.
  - No conversation text, identity or internal Langfuse ID appears in API/DOM/CSV/logs.

## Done When

- Dashboard starts from Freshdesk inventory rather than only Langfuse for this section.
- “Không thấy lần gọi CS-agent” is never merged with “Đã gọi nhưng không có phản hồi/chuyển CS”.
- CS can see whether human CS covered a ticket in the no-call-observed population and drill down to Ticket IDs.
- Existing Langfuse KPI and Ticket Explorer semantics remain unchanged.
- Storage/browser v18, cache v1, resumable private checkpoints, CLI job, refresh script, UI, docs, privacy check and full test gates all pass.
