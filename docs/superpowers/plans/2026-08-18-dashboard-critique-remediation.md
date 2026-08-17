# Dashboard Critique Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sửa 10 phát hiện của đợt đánh giá stakeholder 18/08/2026 — quan trọng nhất là ngừng phơi mã TPE thô ra người đọc nghiệp vụ và tái hiện chỉ số độ tin cậy dữ liệu đã bị mồ côi.

**Architecture:** Phần lớn công việc là **nối lại thứ đã có sẵn**, không xây mới. Status TPE đã tồn tại trong `config/taxonomy.v2.json` nhưng chưa bao giờ tới browser; điểm chất lượng dữ liệu, `selectWeakestCoverage()` và `formatDataAge()` đều đã implement + có test nhưng không được render. Backend resolve status ở `enrichment.py` (nơi có taxonomy) rồi truyền xuống dưới dạng dữ liệu thuần, giữ `dashboard_schema.py` sạch taxonomy đúng như ranh giới hiện hành. Frontend hiển thị, không tự suy diễn.

**Tech Stack:** Python 3.11 + uv (FastAPI, httpx, python-dotenv, uvicorn — đúng 4 runtime dep); React 19.2 + TypeScript 5.9 strict + Vite 8.1 + TanStack Query/Table + Zod 4 + `@visx/scale`/`@visx/shape` + CSS Modules; Node 24 / npm 11; vitest + Playwright.

**Spec:** `docs/superpowers/reports/2026-08-18-stakeholder-persona-critique-report.md` — đọc **cả hai mục Đính chính (§0-bis)** trước khi bắt đầu; chúng thắng bản gốc khi mâu thuẫn.

---

## Global Constraints

Áp dụng cho **mọi** task dưới đây, không nhắc lại trong từng task:

- **Runtime dependency đúng 4**: `fastapi`, `httpx`, `python-dotenv`, `uvicorn`. Không thêm dep Python nào. Frontend không thêm dep nào, không dùng umbrella `@visx/visx`.
- **Ngân sách bundle 250 KB gzip.** Không thêm thư viện chart/tooltip.
- **PII trên browser: chỉ `Ticket ID`.** Cấm tuyệt đối UserID, TransID, số điện thoại, tên/email, nội dung hội thoại, prompt/response, raw payload, `traceId`, `sessionId`.
- **Raw trace/observation không bao giờ serialize ra đĩa.**
- **Zod schema dùng `.strict()`** (`frontend/src/lib/dashboard-schema.ts`). Thêm field vào payload mà quên khai trong Zod → `parse` ném lỗi, dashboard trắng trang. Luôn sửa Zod **cùng lúc** với backend.
- **Bump `_STORAGE_VERSION` phải đi kèm fixture + Zod trong cùng một commit** (`CLAUDE.md`: "fixture và Zod schema phải đi cùng nhau").
- **Không sửa `src/weekly_cs_report/static/legacy/`** (bản rollback) và **không sửa tay `src/weekly_cs_report/static/spa/`** (output của `npm run build`).
- **Sau mọi thay đổi trong `frontend/` phải chạy `npm run build`**, nếu không server vẫn phục vụ bundle cũ.
- **Theme token phải khai ở cả ba khối** trong `frontend/src/styles/global.css`: `:root` (light), `:root[data-theme="dark"]`, và `@media (prefers-color-scheme: dark) > :root:not([data-theme])`. Thiếu một khối là bug theme kinh điển.
- **Copy hướng tới người dùng dùng literal `Zalopay`** (không `ZaloPay`, không `Zalo Pay`).
- **Không thêm metric, filter, route, hay LLM narrative mới** (`PRODUCT.md`). Plan này chỉ *hiển thị* giá trị đã được tính sẵn.
- **Không đảo ngược grain `(transstatus, step_result)`** đã chốt ở projection v5. Ta thêm nhãn **dẫn xuất**, không khôi phục `code/status/case/mapped` cũ.
- **GateGuard** chặn trước lệnh Bash đầu tiên mỗi session và trước mỗi Write/Edit: in đúng facts nó đòi rồi gọi lại **đúng lệnh đó**, không đổi lệnh.
- **Không tuyên bố đã verify Docker** — Docker không chạy được trong môi trường này.

### Lệnh kiểm chứng chuẩn

```bash
# Python (isolated, không đụng .venv chung)
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"

# Frontend
npm run typecheck && npm run test:unit && npm run build

# E2E (cần build trước)
npm run test:e2e

# Ranh giới PII — phải in ra 0
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'
```

---

## Quyết định của PO (18/08/2026) — không tự đổi

| Quyết định | Nội dung |
|---|---|
| Mã TPE chưa có mapping | 10 mã (`-217`, `-268`, `-332`, `-333`, `-367`, `-369`, `-370`, `-380`, `-63`, `-993`) **chỉ ẩn mã thô, không bịa nhãn**. Không suy diễn nghĩa. |
| Đường triển khai | **Bump storage v20 → v21, resolve ở backend.** Không map tĩnh ở frontend (tránh nguồn sự thật thứ hai). |
| Phạm vi | **Toàn bộ 10 item**, tới chi tiết nhỏ nhất. |
| Ngôn ngữ nhãn status | **Giữ nguyên enum tiếng Anh** (`SUCCESSFUL`, `FAILED_NFC`, ...). |

### Deviation đã được PO duyệt — ghi nhận, không phải quên

**Hiển thị enum status tiếng Anh trong câu tiếng Việt** đi ngược hai thứ, và PO đã chọn khi *đã biết* cả hai:

1. `docs/SPEC-v2.md` §5.3 cấm trộn nhãn tiếng Anh trong câu tiếng Việt.
2. Repo đã có convention ngược lại tại `frontend/src/lib/data-quality.ts:5-8`, comment nguyên văn: *"Keep this exhaustive so a newly-added backend enum cannot silently leak implementation language into the dashboard or its CSV exports."*

PO xác nhận giữ tiếng Anh sau khi được trình bày cả hai điểm trên (phiên 18/08/2026). Ghi vào `DESIGN.md` mục Deviations ở Task 13. **Không tự ý dịch sang tiếng Việt.**

---

## Bẫy đã phát hiện — đọc trước khi code

Bốn cái này sẽ làm bạn mất hàng giờ nếu không biết trước. Tất cả đã được kiểm chứng bằng cách chạy thật, không phải suy đoán.

1. **`_tpe_mapping()` (`categories.py:496`) sẽ crash với taxonomy đang chạy.** Nó đọc `mapping["step"]` (số ít, shape **v1**), trong khi runtime load `taxonomy.v2.json` có `steps` (list). Chạy thật: `KeyError: 'step'`. Nó chỉ tới được qua `classify_transfer()` (`categories.py:604`) — hàm **không có caller nào** trong `src/`, tức dead code. Test không bắt được vì `tests/test_categories.py:23` trỏ `taxonomy.v1.json`. **Đừng tái dùng `_tpe_mapping` cho việc resolve mới — viết resolver v2 riêng.**
2. **`dashboard_schema.py` cố ý không biết gì về Taxonomy.** Không import, và comment dòng 1452 ghi rõ "diagnostics no longer interpret exact source signals through taxonomy". **Đừng luồn `Taxonomy` vào đó.** Truyền xuống dữ liệu đã resolve sẵn (dict thuần).
3. **`tpe_code`/`tpe_status_raw`/`tpe_status_canonical` trên `models.py:79-81` là field LEGACY** cho backfill tool riêng (xem docstring `_parse_tpe`, `categories.py:381-385`), **không phải** đường dashboard. Đường dashboard là `tpe_signals` (`models.py:90`), dựng ở `enrichment.py:146`. Đừng sửa nhầm.
4. **Zod `.strict()`** — xem Global Constraints.

---

## File Structure

| File | Trách nhiệm sau khi xong |
|---|---|
| `src/weekly_cs_report/tpe_status.py` *(mới)* | Resolver thuần: `(transstatus, step_result, taxonomy) → status \| None`. Một việc duy nhất, test được độc lập. |
| `src/weekly_cs_report/enrichment.py` | Dựng thêm bảng tra `(transstatus, step_result) → status` cho đúng các cặp quan sát được. |
| `src/weekly_cs_report/dashboard_schema.py` | Mang `status` qua `tpe_rows`; bump `_STORAGE_VERSION` 20 → 21. Vẫn không biết taxonomy. |
| `frontend/src/lib/dashboard-schema.ts` | Zod: thêm `status` nullable vào phần tử `tpe`. |
| `frontend/test/fixtures/dashboard.ts` | Fixture khớp v21. |
| `frontend/src/lib/selectors.ts` | Dựng nhãn tín hiệu từ `status`, không từ mã thô. |
| `frontend/src/lib/narrative.ts` | Câu insight không còn chứa mã thô. |
| `frontend/src/components/TransferDiagnostics.tsx` | Bảng có cột status + cảnh báo mẫu nhỏ. |
| `frontend/src/components/AppShell.tsx` | Hiện điểm độ tin cậy + nav CSAT. |
| `frontend/src/components/DecisionLedger.tsx` | Affordance độ tin cậy theo từng KPI. |
| `frontend/src/lib/format.ts` | Hằng số ngưỡng mẫu nhỏ dùng chung. |

---

## Task 1: Resolver status TPE (thuần, không side effect)

**Files:**
- Create: `src/weekly_cs_report/tpe_status.py`
- Test: `tests/test_tpe_status.py` (mới)

**Interfaces:**
- Consumes: `weekly_cs_report.categories.Taxonomy` (field `tpe_mappings`, mỗi phần tử là mapping có `code`, `steps`, `case`, `status`).
- Produces: `resolve_tpe_status(transstatus: str, step_result: str | None, taxonomy: Taxonomy) -> str | None` — Task 2 dùng.

- [ ] **Step 1: Viết test thất bại**

```python
# tests/test_tpe_status.py
from pathlib import Path

import pytest

from weekly_cs_report.categories import load_taxonomy
from weekly_cs_report.tpe_status import resolve_tpe_status

TAXONOMY_V2 = Path(__file__).parents[1] / "config" / "taxonomy.v2.json"


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy(TAXONOMY_V2)


def test_resolves_step_specific_pair(taxonomy):
    assert resolve_tpe_status("1", "1", taxonomy) == "SUCCESSFUL"


def test_resolves_code_with_empty_steps_regardless_of_step(taxonomy):
    # -374 mang mapping steps rong, nen moi step deu ra REFUNDING.
    assert resolve_tpe_status("-374", "-9999", taxonomy) == "REFUNDING"
    assert resolve_tpe_status("-374", None, taxonomy) == "REFUNDING"


def test_returns_none_for_unmapped_code(taxonomy):
    # -217 khong co trong taxonomy; khong duoc doan nghia.
    assert resolve_tpe_status("-217", "-5025", taxonomy) is None


def test_returns_none_when_step_specific_code_lacks_step(taxonomy):
    # -244 chi co mapping step-specific, thieu step thi khong ket luan.
    assert resolve_tpe_status("-244", None, taxonomy) is None


def test_never_raises_on_v2_shape(taxonomy):
    # Hoi quy cho bay _tpe_mapping: KeyError 'step' tren taxonomy v2.
    for code in ("1", "-217", "-365", "-993"):
        resolve_tpe_status(code, None, taxonomy)
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `uv run --isolated --extra dev --locked pytest tests/test_tpe_status.py -q --basetemp="$(mktemp -d)"`
Expected: FAIL — `ModuleNotFoundError: No module named 'weekly_cs_report.tpe_status'`

- [ ] **Step 3: Viết implementation tối thiểu**

```python
# src/weekly_cs_report/tpe_status.py
"""Resolve the governed TPE status for an observed (transstatus, step_result).

The mapping table lives in ``config/taxonomy.v2.json`` under ``tpe.mappings``.
This module only reads it; it never widens, guesses, or back-fills a status.

Do not reuse ``categories._tpe_mapping`` here: that helper reads the v1 key
``step`` and raises ``KeyError`` against the v2 taxonomy the runtime loads.
"""

from __future__ import annotations

from .categories import Taxonomy


def resolve_tpe_status(
    transstatus: str, step_result: str | None, taxonomy: Taxonomy
) -> str | None:
    """Return the governed status, or ``None`` when the pair is not mapped.

    A mapping whose ``steps`` is empty applies to the code regardless of the
    step.  A mapping with entries applies only when ``step_result`` is one of
    them.  The v2 taxonomy has been verified to contain no code carrying both
    shapes and no ``(code, step)`` pair resolving to two different statuses, so
    the first match is the only match.

    ``None`` means "not mapped" and must stay unlabelled downstream.  The
    taxonomy's ``unmapped_policy = passthrough`` governs storage, never display.
    """
    for mapping in taxonomy.tpe_mappings:
        if mapping["code"] != transstatus:
            continue
        steps = mapping.get("steps") or ()
        if not steps:
            return str(mapping["status"])
        if step_result is not None and step_result in steps:
            return str(mapping["status"])
    return None
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `uv run --isolated --extra dev --locked pytest tests/test_tpe_status.py -q --basetemp="$(mktemp -d)"`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/weekly_cs_report/tpe_status.py tests/test_tpe_status.py
git commit -m "feat: add v2-safe TPE status resolver"
```

---

## Task 2: Đưa status vào payload, bump storage v21

Đây là thay đổi **hợp đồng dữ liệu**. Backend, Zod và fixture phải đi cùng một commit, nếu không dashboard trắng trang giữa hai task.

**Files:**
- Modify: `src/weekly_cs_report/enrichment.py` (nơi có taxonomy)
- Modify: `src/weekly_cs_report/dashboard_schema.py:33` (`_STORAGE_VERSION`) và `:1250-1265` (`tpe_rows`)
- Modify: `frontend/src/lib/dashboard-schema.ts:331-339` (Zod block `tpe`)
- Modify: `frontend/test/fixtures/dashboard.ts`
- Test: `tests/test_dashboard_schema.py`, `frontend/test/dashboard-schema.test.ts`

**Interfaces:**
- Consumes: `resolve_tpe_status()` từ Task 1.
- Produces: mỗi phần tử `transfer_reasons.tpe` có thêm `status: str | None`. Task 3–5 dùng field này.

- [ ] **Step 1: Viết test backend thất bại**

Thêm vào `tests/test_dashboard_schema.py`:

```python
def test_tpe_rows_carry_resolved_status_and_leave_unmapped_null():
    """Status phai di kem tung dong, va cap chua map phai la None."""
    rows = _tpe_rows_from_signals(
        {("1", "1"): 19, ("-217", "-5025"): 2},
        {("1", "1"): "SUCCESSFUL"},
    )
    by_pair = {(r["transstatus"], r["step_result"]): r for r in rows}
    assert by_pair[("1", "1")]["status"] == "SUCCESSFUL"
    assert by_pair[("-217", "-5025")]["status"] is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `uv run --isolated --extra dev --locked pytest tests/test_dashboard_schema.py -k tpe_rows_carry -q --basetemp="$(mktemp -d)"`
Expected: FAIL — hàm chưa tồn tại.

- [ ] **Step 3: Backend — dựng bảng tra ở `enrichment.py`**

`enrichment.py` đã có `taxonomy` (tham số dòng 58 và 271) và dựng `tpe_signals` ở dòng 146. Thêm hàm dựng bảng tra **chỉ cho các cặp thật sự quan sát được** (không xuất cả taxonomy ra ngoài):

```python
# src/weekly_cs_report/enrichment.py  — them vao cuoi file
from .tpe_status import resolve_tpe_status


def build_tpe_status_index(
    sessions: Sequence[SessionRecord], taxonomy: Taxonomy
) -> dict[tuple[str, str | None], str]:
    """Map every observed (transstatus, step_result) to its governed status.

    Only observed pairs are included, so the payload never ships the taxonomy
    itself.  Unmapped pairs are omitted entirely — absence means "not mapped",
    which the browser renders as unclassified rather than guessing.
    """
    index: dict[tuple[str, str | None], str] = {}
    for session in sessions:
        for pair in session.dimensions.tpe_signals:
            if pair in index:
                continue
            status = resolve_tpe_status(pair[0], pair[1], taxonomy)
            if status is not None:
                index[pair] = status
    return index
```

- [ ] **Step 4: Backend — mang status qua `tpe_rows`**

Trong `src/weekly_cs_report/dashboard_schema.py`, sửa `_transfer_reasons` (bắt đầu dòng 1223) để nhận thêm tham số `tpe_status_index: Mapping[tuple[str, str | None], str]` và đổi khối `tpe_rows` (dòng 1250-1265) thành:

```python
    tpe_rows = [
        {
            "transstatus": transstatus,
            "step_result": step_result,
            "count": count,
            # None = cap chua co trong taxonomy.  Browser hien "chua phan loai";
            # khong bao gio suy dien nghia tu con so.
            "status": tpe_status_index.get((transstatus, step_result)),
        }
        for (transstatus, step_result), count in sorted(
            tpe_counts.items(),
            key=lambda item: (
                -item[1],
                item[0][0],
                item[0][1] is None,
                item[0][1] or "",
            ),
        )
    ]
```

`dashboard_schema.py` vẫn **không** import `Taxonomy` — nó chỉ nhận một dict thuần. Ranh giới kiến trúc giữ nguyên.

Cập nhật mọi caller của `_transfer_reasons` để truyền index (dựng ở tầng pipeline, nơi taxonomy sẵn có). Rồi bump dòng 33:

```python
_STORAGE_VERSION = 21
```

- [ ] **Step 5: Frontend — Zod (bắt buộc cùng commit)**

`frontend/src/lib/dashboard-schema.ts`, khối `tpe` dòng 331-339 — object đang `.strict()` nên **phải** khai field mới:

```ts
    tpe: z.array(
      z
        .object({
          transstatus: tpeToken,
          step_result: tpeToken.nullable(),
          count: positiveInteger,
          // null = cap chua co trong taxonomy TPE.
          status: z.string().min(1).nullable(),
        })
        .strict(),
    ),
```

- [ ] **Step 6: Frontend — fixture khớp v21**

Trong `frontend/test/fixtures/dashboard.ts`, thêm `status` vào **mọi** phần tử `tpe` (ít nhất một dòng có status thật và một dòng `null`, để test phủ cả hai nhánh).

- [ ] **Step 7: Chạy toàn bộ, xác nhận pass**

```bash
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
npm run typecheck && npm run test:unit
```
Expected: tất cả PASS. Nếu Zod ném `unrecognized_key` → fixture và schema lệch nhau.

- [ ] **Step 8: Kiểm ranh giới PII**

```bash
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'
```
Expected: `0`

- [ ] **Step 9: Commit**

```bash
git add src/weekly_cs_report/enrichment.py src/weekly_cs_report/dashboard_schema.py \
        frontend/src/lib/dashboard-schema.ts frontend/test/fixtures/dashboard.ts \
        tests/test_dashboard_schema.py
git commit -m "feat: carry resolved TPE status in payload (storage v21)"
```

---

## Task 3: Câu insight ngừng phơi mã thô

Đây là item nghiêm trọng nhất của report: câu tự sinh in `Transstatus -217 / Step result -5025` thẳng cho C-level.

**Files:**
- Modify: `frontend/src/lib/selectors.ts:111-121` (`selectTransferSignals`)
- Test: `frontend/test/narrative.test.ts`

**Interfaces:**
- Consumes: `status` trên mỗi dòng `transfer_reasons.tpe` (Task 2).
- Produces: `NarrativeSignal.label` không bao giờ chứa mã thô.

- [ ] **Step 1: Viết test thất bại**

```ts
// frontend/test/narrative.test.ts
it("khong bao gio in ma TPE tho trong cau insight", () => {
  const signals = selectTransferSignals({
    transfer_reasons: {
      ...baseTransferReasons,
      tpe: [
        { transstatus: "1", step_result: "1", count: 19, status: "SUCCESSFUL" },
        { transstatus: "-217", step_result: "-5025", count: 2, status: null },
      ],
    },
  });
  const labels = signals.map((s) => s.label).join(" | ");
  expect(labels).toContain("SUCCESSFUL");
  expect(labels).not.toMatch(/-217|-5025|Transstatus|Step result/);
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- narrative`
Expected: FAIL — label hiện tại là `"Transstatus -217 / Step result -5025"`.

- [ ] **Step 3: Implement**

Thay `selectTransferSignals` (`frontend/src/lib/selectors.ts:111-121`):

```ts
/**
 * Observed transfer signals, most frequent first.
 *
 * TPE codes are operational observations, not proven causes.  Only rows the
 * taxonomy could resolve carry a signal: a raw code means nothing to a CS or
 * exec reader, and this string is copied into their own reports verbatim.
 * Unresolved rows stay in the diagnostics table, where the count is the point.
 */
export function selectTransferSignals(view: {
  readonly transfer_reasons: DashboardView["transfer_reasons"];
}): NarrativeSignal[] {
  const tpe = view.transfer_reasons.tpe
    .filter((item) => item.status !== null)
    .map((item) => ({ label: item.status as string, count: item.count }));
  return tpe.sort((left, right) => right.count - left.count);
}
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit -- narrative`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/selectors.ts frontend/test/narrative.test.ts
git commit -m "fix: stop leaking raw TPE codes into the generated insight line"
```

---

## Task 4: Bảng Chẩn đoán hiện status + gộp nhóm chưa phân loại

**Files:**
- Modify: `frontend/src/components/TransferDiagnostics.tsx:120-215` (bảng Transstatus/Step result)
- Test: `frontend/test/dashboard-screen.test.tsx`

**Interfaces:**
- Consumes: `status` (Task 2).
- Produces: không có export mới.

- [ ] **Step 1: Viết test thất bại**

```tsx
it("hien status da resolve va gan nhan chua phan loai cho phan con lai", () => {
  renderDiagnostics({
    tpe: [
      { transstatus: "1", step_result: "1", count: 19, status: "SUCCESSFUL" },
      { transstatus: "-217", step_result: "-5025", count: 2, status: null },
    ],
  });
  expect(screen.getByText("SUCCESSFUL")).toBeInTheDocument();
  expect(screen.getByText("Chưa phân loại")).toBeInTheDocument();
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- dashboard-screen`
Expected: FAIL — chưa có cột status.

- [ ] **Step 3: Implement**

Thêm một cột `Trạng thái` là cột **đầu tiên** của bảng (người đọc gặp nghĩa trước, mã sau). Giữ nguyên hai cột mã cho dev tra cứu. Với `status === null`, render `Chưa phân loại`.

Copy đặt trong caption của bảng, ngay dưới `<caption>` hiện có:

> `Trạng thái lấy từ bảng TPE của taxonomy. "Chưa phân loại" nghĩa là cặp mã chưa có trong bảng — không phải lỗi giao dịch.`

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit -- dashboard-screen`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/TransferDiagnostics.tsx frontend/test/dashboard-screen.test.tsx
git commit -m "feat: show governed TPE status in the diagnostics table"
```

---

## Task 5: Bộ lọc Transstatus trong Ticket Explorer

Dropdown đang liệt kê 20 mã trần (`TicketExplorer.tsx:640`, nhãn từ `dashboard-filters.ts:65`).

**Files:**
- Modify: `frontend/src/components/TicketExplorer.tsx:636-650`
- Test: `frontend/test/dashboard-filters.test.ts`

- [ ] **Step 1: Viết test thất bại**

```ts
it("nhan option Transstatus uu tien status, giu ma trong ngoac", () => {
  expect(tpeOptionLabel({ transstatus: "1", step_result: "1", status: "SUCCESSFUL" }))
    .toBe("SUCCESSFUL (1 / 1)");
  expect(tpeOptionLabel({ transstatus: "-217", step_result: "-5025", status: null }))
    .toBe("Chưa phân loại (-217 / -5025)");
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- dashboard-filters`
Expected: FAIL — `tpeOptionLabel` chưa tồn tại.

- [ ] **Step 3: Implement**

Thêm `tpeOptionLabel()` vào `frontend/src/lib/dashboard-filters.ts` và dùng nó cho option của dropdown. Ở đây **giữ mã trong ngoặc** vì đây là công cụ điều tra của dev/CS, khác câu prose hướng tới lãnh đạo ở Task 3.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit -- dashboard-filters`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/dashboard-filters.ts frontend/src/components/TicketExplorer.tsx frontend/test/dashboard-filters.test.ts
git commit -m "feat: label Transstatus filter options by governed status"
```

---

## Task 6: Hiện lại điểm độ tin cậy dữ liệu (đang bị vứt)

`AppShell.tsx:126-127` gọi `calculateDataQualityScore(snapshot)` rồi chỉ dùng `.ageMs`; `.score` và `.tone` bị bỏ. CSS `.quality`, `.qualityWarning` (`dashboard.module.css:96-121`) đã có sẵn nhưng không component nào tham chiếu.

**Files:**
- Modify: `frontend/src/components/AppShell.tsx:250-290`
- Test: `frontend/test/data-quality-score.test.ts`, `frontend/test/dashboard-screen.test.tsx`

- [ ] **Step 1: Viết test thất bại**

```tsx
it("hien diem do tin cay canh chip trang thai", () => {
  renderShell({ coverage: { issue_category: 0.856, tpe: 0.783, skill: 0.704, app: 0.8, intent: 0.78 } });
  const chip = screen.getByTestId("qualityChip");
  expect(chip).toHaveTextContent(/Độ tin cậy/);
  expect(chip).toHaveAttribute("data-tone", "warning");
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- dashboard-screen`
Expected: FAIL — không có `qualityChip`.

- [ ] **Step 3: Implement**

Dùng `snapshotQuality.score` và `.tone` **đã được tính sẵn** ở dòng 127. Render chip cạnh `#statusChip`, tái dùng class `.quality`/`.qualityWarning` đang mồ côi. Copy: `Độ tin cậy {score}/100`. `data-tone` nhận `good` | `warning` | `critical` để CSS bắt.

Không tính lại điểm, không đổi trọng số 40/20/20/10/10 — đó là công thức governed đã có test.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit -- dashboard-screen`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/test/dashboard-screen.test.tsx
git commit -m "feat: surface the governed data-quality score in the shell"
```

---

## Task 7: Affordance độ tin cậy theo từng KPI

`selectWeakestCoverage()` (`selectors.ts:218-238`) đã implement + có test (`decision-scope.test.tsx:17,198,216`) nhưng **không được render ở đâu**.

**Files:**
- Modify: `frontend/src/lib/selectors.ts` (`LedgerCell`, `selectLedger`), `frontend/src/components/DecisionLedger.tsx:107-139`
- Test: `frontend/test/decision-scope.test.tsx`

**Cảnh báo:** `DecisionLedger.tsx` có **hai nhánh render gần giống hệt** (`:109-119` không tương tác, `:121-137` có `<button>`). Slot mới **phải thêm ở cả hai**. Nhánh tương tác bọc trong `<button>` nên **không được** đặt phần tử tương tác lồng vào trong.

- [ ] **Step 1: Viết test thất bại**

```tsx
it("gan chu thich do phu vao o KPI yeu nhat", () => {
  renderLedger({ coverage: { issue_category: 0.856, tpe: 0.783, skill: 0.704, app: 0.9, intent: 0.9 } });
  expect(screen.getByText(/Độ phủ Skill 70/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- decision-scope`
Expected: FAIL

- [ ] **Step 3: Implement**

Thêm field optional `coverageNote?: string | null` vào `LedgerCell` (`selectors.ts:239-256`), điền trong `selectLedger` bằng kết quả `selectWeakestCoverage()`, render dưới `.ledgerSupport` ở **cả hai** nhánh. Chỉ hiện khi độ phủ dưới `COVERAGE_BADGE_FLOOR` (0.8) — đã có sẵn hằng số ở `selectors.ts:202`.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit -- decision-scope`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/selectors.ts frontend/src/components/DecisionLedger.tsx frontend/test/decision-scope.test.tsx
git commit -m "feat: attach weakest-coverage note to the KPI ledger"
```

---

## Task 8: Cảnh báo mẫu nhỏ ở bảng Chẩn đoán và bảng segment

Convention **đã có** ở `CsatBreakdownTable.tsx`: `PERCENTAGE_SAMPLE_MINIMUM = 20` (dòng 20), badge "Mẫu nhỏ" (`:173-178`), tụt về count khi dưới ngưỡng (`:57-61`). **Tái dùng ngưỡng 20, không tạo ngưỡng 10 thứ hai.**

**Files:**
- Modify: `frontend/src/lib/format.ts` (nâng hằng số lên dùng chung), `frontend/src/components/CsatBreakdownTable.tsx:20` (import thay vì khai local), `frontend/src/components/TransferDiagnostics.tsx:46-48`, `frontend/src/components/BelowFold.tsx:554-557`
- Test: `frontend/test/format.test.ts`

- [ ] **Step 1: Viết test thất bại**

```ts
it("giau ty le khi mau duoi nguong va giu nguyen so dem", () => {
  expect(shareWithSampleGuard(3, 8)).toBe("3");
  expect(shareWithSampleGuard(30, 200)).toBe("30 · 15,0%");
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- format`
Expected: FAIL — `shareWithSampleGuard` chưa tồn tại.

- [ ] **Step 3: Implement**

Đưa `PERCENTAGE_SAMPLE_MINIMUM` vào `frontend/src/lib/format.ts`, export `shareWithSampleGuard(count, denominator)`. Sửa `CsatBreakdownTable.tsx` import hằng số dùng chung (**không đổi hành vi hiện tại của nó**). Áp cho `formatTransferShare` (`TransferDiagnostics.tsx:46-48`) và `formatMetric` (`BelowFold.tsx:554-557`).

Với bảng Chẩn đoán, gate theo `item.count` (tử số), **không** theo `observed_transfer_denominator` — mẫu số ở đây là toàn bảng, khác ngữ nghĩa CSAT.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit -- format && npm run test:unit`
Expected: PASS, và test CSAT cũ **không đổi kết quả**.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/format.ts frontend/src/components/CsatBreakdownTable.tsx \
        frontend/src/components/TransferDiagnostics.tsx frontend/src/components/BelowFold.tsx \
        frontend/test/format.test.ts
git commit -m "feat: reuse the small-sample guard in transfer and segment tables"
```

---

## Task 9: Thêm CSAT vào thanh điều hướng

`CsatSection.tsx:451` render `id="csat"` nhưng `SECTIONS` (`AppShell.tsx:52-59`) không có entry — người dùng không biết mục này tồn tại.

**Files:**
- Modify: `frontend/src/components/AppShell.tsx:52-59`
- Test: `frontend/test/dashboard-screen.test.tsx`

- [ ] **Step 1: Viết test thất bại**

```tsx
it("co link dieu huong toi muc CSAT", () => {
  renderShell();
  expect(screen.getByRole("link", { name: "Mức hài lòng" })).toHaveAttribute("href", "#csat");
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- dashboard-screen`
Expected: FAIL

- [ ] **Step 3: Implement**

Chèn vào `SECTIONS` **đúng thứ tự DOM** (giữa `segments` và `diagnostics`, khớp thứ tự render ở `BelowFold.tsx`):

```ts
  { id: "segments", label: "So sánh segment" },
  { id: "csat", label: "Mức hài lòng" },
  { id: "diagnostics", label: "Chẩn đoán" },
```

Scroll-spy ở `AppShell.tsx:145-160` tự động chạy theo `SECTIONS`, không cần sửa thêm.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit -- dashboard-screen`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/test/dashboard-screen.test.tsx
git commit -m "feat: add the CSAT section to the shell navigation"
```

---

## Task 10: Đặt `id` cho control còn thiếu (mức Nhẹ — đã hạ cấp)

**Đọc kỹ:** cả 12 control đều đã nằm trong `<label>` bọc ngoài, nên **đã có accessible name** — screen reader đọc đúng. Đây **không** phải lỗi WCAG 4.1.2. Việc cần làm chỉ là thêm `id` cho `htmlFor`, độ ổn định `getByLabel` của Playwright, và autofill; đồng thời xoá sự thiếu nhất quán (11/15 control trong `TicketExplorer` đã có `id`, 4 cái cùng hình dạng thì không).

**Files:**
- Modify: `TicketExplorer.tsx:525,534,548,836`, `CsatSection.tsx:282,299,316,335`, `CsatBreakdownTable.tsx:105`, `FreshdeskCookieDialog.tsx:119`, `ReportScopePicker.tsx:106`, `TraceExplainer.tsx:300`
- Test: `frontend/test/dashboard-screen.test.tsx`

- [ ] **Step 1: Viết test thất bại**

```tsx
it("moi control loc deu co id on dinh", () => {
  renderExplorer();
  ["ticketIdInput", "outcomeInput", "csatSatisfactionInput"].forEach((id) => {
    expect(document.getElementById(id)).not.toBeNull();
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `npm run test:unit -- dashboard-screen`
Expected: FAIL

- [ ] **Step 3: Implement**

Đặt `id` theo đúng quy ước đang dùng trong chính file đó (`cohortWeekInput`, `tpeCodeInput`, ... → thêm `ticketIdInput`, `outcomeInput`, `csatSatisfactionInput`). Với control render theo vòng lặp (checkbox chọn cột `:836`, checkbox tuần `ReportScopePicker:106`), dùng id có tiền tố ổn định: `` `columnOption-${column.key}` ``, `` `reportScope-${week.cohort_week}` ``. Thêm `htmlFor` tương ứng khi `<label>` đã có sẵn text.

**Không** thêm `aria-label` — sẽ ghi đè tên đang đúng từ `<label>` và làm giọng đọc tệ hơn.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `npm run test:unit && npm run test:e2e`
Expected: PASS (e2e có `@axe-core/playwright`, phải không phát sinh vi phạm mới)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/
git commit -m "chore: give every filter control a stable id"
```

---

## Task 11: Quyết định màu `critical` + dọn CSS chết

`--critical` (`global.css:54,100,124`) có **0 consumer sống** — chỉ dùng ở class chết `.criticalAction` (`below-fold.module.css:29-30`). `--critical-text` có 2 consumer sống. Guideline Zalopay **không có màu đỏ nào**, nên `#b42318` là deviation chưa được công bố.

**Files:**
- Modify: `frontend/src/styles/global.css`, `frontend/src/components/below-fold.module.css:29-30`
- Test: quan sát trực quan hai theme

- [ ] **Step 1: Xoá class chết**

Xoá `.criticalAction` khỏi `below-fold.module.css` (đã xác nhận không nơi nào tham chiếu trong `frontend/src`).

- [ ] **Step 2: Xác nhận `--critical` thành token mồ côi**

```bash
grep -rn "var(--critical)" frontend/src/
```
Expected: không kết quả. Nếu còn, dừng lại và giữ token.

- [ ] **Step 3: Xoá `--critical` khỏi cả ba khối theme**

Xoá dòng `54`, `100`, `124` trong `global.css`. **Giữ nguyên `--critical-text`** — nó có consumer thật và đỏ là cần thiết về mặt ngữ nghĩa (mức "Rất tệ" của CSAT, KPI critical), đúng tinh thần Product Principle 4: không hy sinh sự thật để đẹp hơn.

- [ ] **Step 4: Kiểm hai theme**

Run: `npm run build`, mở `http://127.0.0.1:8765/`, đổi qua lại Sáng/Tối, xác nhận badge "Rất tệ" và KPI critical vẫn đỏ đúng.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/global.css frontend/src/components/below-fold.module.css
git commit -m "chore: drop the unused --critical token and its dead class"
```

---

## Task 12: Đo lại tap target trên mobile + truy nguồn `eval()`

Hai việc điều tra, không phải sửa mù. Cả hai đều **có thể kết luận là không có vấn đề** — đó là kết quả hợp lệ, ghi lại rồi đóng.

**Files:**
- Create: `docs/superpowers/reports/2026-08-18-mobile-and-csp-followup.md`

- [ ] **Step 1: Đo tap target riêng vùng Ticket Explorer trên mobile**

Emulate `390x844x3,mobile,touch`, cuộn tới Ticket Explorer, chạy:

```js
Array.from(document.querySelectorAll('#tickets button, #tickets a, #tickets input, #tickets select'))
  .map(el => { const r = el.getBoundingClientRect();
    return { tag: el.tagName, text: (el.textContent||'').trim().slice(0,24),
             w: Math.round(r.width), h: Math.round(r.height) }; })
  .filter(x => x.w > 0 && x.h > 0 && (x.w < 44 || x.h < 44));
```

Số tổng toàn trang (9% trên mobile) **không** thay cho phép đo riêng vùng này — checkbox và link ticket dày đặc nhất ở đây.

- [ ] **Step 2: Truy nguồn vi phạm CSP `eval`**

Grep bundle đã cho `eval(` = 0 và `new Function` = 0, nên literal không khớp. Dựng bundle có sourcemap rồi lần theo `index-*.js:8` cột ~78772:

```bash
npm run build -- --sourcemap
```

Nghi phạm khả dĩ nhất theo thứ tự: `zod` (dựng validator động), `@tanstack/*`, rồi React DevTools hook. Nếu đường code đó không thuộc tính năng nào đang dùng, ghi lại là vô hại và đóng — CSP đang chặn đúng việc của nó.

- [ ] **Step 3: Ghi kết quả**

Viết report ngắn: đo được gì, kết luận gì, còn treo gì. Nếu tap target đạt và `eval` vô hại thì nói thẳng như vậy.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/reports/2026-08-18-mobile-and-csp-followup.md
git commit -m "docs: record mobile tap-target and CSP eval findings"
```

---

## Task 13: Đồng bộ tài liệu với code

Tài liệu đang mô tả sai thứ đang chạy.

**Files:**
- Modify: `DESIGN.md:188` và mục Deviations, `CLAUDE.md`, `frontend/src/components/BelowFold.tsx:746-749`

- [ ] **Step 1: Sửa comment lạc trong code**

`BelowFold.tsx:746-749` vẫn ghi component này lo "the data-quality disclosure" — mục đó đã bị xoá ở commit `3619c42`. Sửa docstring cho khớp thực tế (trends, segment, transfer diagnostics).

- [ ] **Step 2: Sửa `DESIGN.md`**

- Dòng `188`: bỏ "⑤ Data quality" khỏi Surface composition, thay bằng thứ tự thật: trends → segment → CSAT → diagnostics → Ticket Explorer.
- Ghi rõ câu hỏi "dữ liệu này tin được không" nay được trả lời bằng chip độ tin cậy ở shell (Task 6) + chú thích độ phủ theo KPI (Task 7).
- Thêm vào mục Deviations, nguyên văn:

```markdown
9. Nhãn trạng thái TPE hiển thị bằng enum tiếng Anh (`SUCCESSFUL`, `FAILED_NFC`, ...)
   thay vì dịch sang tiếng Việt. Đi ngược SPEC-v2 §5.3 (cấm trộn nhãn tiếng Anh
   trong câu tiếng Việt) và ngược convention `DATA_QUALITY_LABELS`
   (`frontend/src/lib/data-quality.ts:5-8`). PO quyết định giữ tiếng Anh ngày
   2026-08-18 sau khi được trình bày cả hai điểm trên. Xem lại nếu có phản hồi
   từ người dùng CS.

10. `--critical: #b42318` (đã gỡ ở bản này) và `--critical-text: #b42318` là màu đỏ
    không có trong palette Zalopay — guideline không có màu đỏ nào. Giữ lại vì
    ngữ nghĩa cảnh báo, theo Product Principle 4.
```

- [ ] **Step 3: Sửa `CLAUDE.md`**

- Cập nhật `_STORAGE_VERSION` sang **21** ở mọi chỗ mô tả (hiện tài liệu dừng ở v18, code đã v20 trước khi bắt đầu plan này).
- Thêm vào mục bẫy: `categories._tpe_mapping()` là code chết mang lỗi tương thích v1/v2 (`KeyError: 'step'` với taxonomy v2); chỉ tới được qua `classify_transfer()` vốn không có caller; `tests/test_categories.py` trỏ `taxonomy.v1.json` nên không bắt được.

- [ ] **Step 4: Kiểm chứng**

```bash
grep -rn "Data quality\|⑤" DESIGN.md
grep -rn "_STORAGE_VERSION\|v18" CLAUDE.md
```
Expected: không còn mô tả mục đã xoá; số version khớp `dashboard_schema.py:33`.

- [ ] **Step 5: Commit**

```bash
git add DESIGN.md CLAUDE.md frontend/src/components/BelowFold.tsx
git commit -m "docs: sync design and project docs with the shipped surface"
```

---

## Kiểm tra cuối trước khi giao

- [ ] Toàn bộ suite xanh:

```bash
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
npm run typecheck && npm run test:unit && npm run build && npm run test:e2e
```

- [ ] Ranh giới PII in ra `0`.
- [ ] Mở dashboard thật, xác nhận bằng mắt: câu insight **không còn** chuỗi nào khớp `/Transstatus|-\d{3}/`; chip độ tin cậy hiện đúng tone; nav có "Mức hài lòng"; hai theme đều đọc được.
- [ ] `git log --oneline` cho thấy các commit nhỏ, một deliverable mỗi commit.
- [ ] **Không** claim đã verify Docker.
- [ ] **Không** claim bản build là "official" — cần UXD/Brand + Design System ký duyệt, chưa có.

---

## Self-review

**Phủ spec:** 10 item của report → Task 3+4+5 (item 1), Task 6 (item 2), Task 13 (item 3), Task 9 (item 4), Task 10 (item 5), Task 8 (item 6), Task 12 (item 7 và 8), Task 11 (item 9), Task 7 (item 10). Task 1–2 là hạ tầng bắt buộc cho item 1. Không item nào thiếu task.

**Nhất quán kiểu:** `resolve_tpe_status()` (Task 1) → `build_tpe_status_index()` (Task 2) → field `status` trong `tpe_rows` → `status` trong Zod → `item.status` ở `selectors.ts`/`TransferDiagnostics`/`dashboard-filters`. Cùng một tên xuyên suốt.

**Rủi ro còn lại:** 28,1% tín hiệu TPE tuần 10/08 không resolve được, nên câu insight sẽ ngắn hơn hiện tại — đó là **đúng ý đồ**, không phải hồi quy. Nếu về sau muốn phủ hết, cần nghĩa nghiệp vụ của 10 mã còn thiếu từ team thanh toán, rồi bổ sung vào `taxonomy.v2.json` (không cần đổi code).
