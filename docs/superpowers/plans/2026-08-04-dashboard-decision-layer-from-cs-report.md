# Dashboard Decision Layer From CS Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Giúp CS/PO nhìn thấy việc cần kiểm tra trong phạm vi đang chọn và đi thẳng tới các ticket liên quan, mà không thêm metric suy đoán hoặc lặp lại dashboard.

**Architecture:** Frontend-only. Tất cả insight được suy ra từ `DashboardSnapshot` hiện có và từ đúng report scope đã chọn. Không đổi payload, backend, storage version hay Freshdesk job.

**Tech Stack:** React 19, TypeScript strict, Vitest/Testing Library, CSS Modules.

**Revision 2026-08-04:** PO removed the proposed Category focus cards after implementation review. The existing sortable Category table remains the only Category presentation.

## Global Constraints

- Không dùng các kết luận `AI lỗi`, `AI không làm được`, `chuyển đúng rule`, `CS workload thực tế` nếu payload không chứng minh được.
- Không dùng ước tính tác động, causal claim hoặc ngưỡng mới.
- Luôn hiển thị count trước, rate sau; rate phải có mẫu số xác định.
- Mọi insight phải dùng cùng scope với title/KPI: một tuần, nhiều tuần đã chọn hoặc toàn kỳ.
- Click insight chỉ đổi filter cục bộ của Ticket Explorer; không đổi global report scope.
- Tối đa 3 mục trong “Cần xem trong phạm vi này”.
- Không thêm funnel, action tracker, bảng tần suất reply hay dependency mới.

---

### Task 1: Biến rail cảnh báo thành danh sách có hành động

**Files:**
- Modify: `frontend/src/lib/selectors.ts`
- Modify: `frontend/src/components/DecisionLedger.tsx`
- Modify: `frontend/src/components/dashboard.module.css`
- Test: `frontend/test/decision-scope.test.tsx`

**Interface:**

```ts
interface AttentionItem {
  readonly id: string;
  readonly severity: "critical" | "warning";
  readonly headline: string;
  readonly action: string;
  readonly filterPatch: Partial<TicketFilters> | null;
  readonly targetSection: "quality" | null;
}
```

- [ ] Import `TicketFilters` vào `selectors.ts` và bổ sung hai field trên.
- [ ] Giữ đúng ba signal hiện có, không tạo alert mới:
  - `attention-gt4`: `{ gt4_turn: "true", transferred: "false" }`, `targetSection: null`.
  - `attention-gate`: `filterPatch: null`, `targetSection: "quality"`.
  - `attention-enrichment`: `filterPatch: null`, `targetSection: "quality"`.
- [ ] Trả tối đa ba item bằng `items.slice(0, 3)`; selector tiếp tục lấy số từ `selectScope(...)`.
- [ ] Đổi accessible label từ `Việc cần chú ý` thành `Cần xem trong phạm vi này`.
- [ ] Với `filterPatch`, render nút `Xem ticket` và gọi prop `onCellSelect` đang có. `DashboardScreen` đã truyền `applyLedgerFilter`, nên scope và hành vi scroll được giữ nguyên mà không cần sửa thêm wiring.
- [ ] Với `targetSection`, render link `Kiểm tra dữ liệu` tới `#quality`. Không render CTA nếu cả hai field đều `null`.
- [ ] Test duy nhất cần thêm: selected week có `gt4WithoutCs = 0` không được lấy warning từ tuần khác; khi có warning, click `Xem ticket` phát đúng patch `{gt4_turn: "true", transferred: "false"}`.

Run:

```bash
cd frontend
npx vitest run test/decision-scope.test.tsx
```

---

### Task 2: Category focus — removed by PO decision

Không triển khai. Giữ bảng `SegmentTable` hiện tại với sort và filter từng giá trị.

---

### Task 3: Gate giao hàng tối thiểu

- [ ] Kiểm tra không có copy bị cấm:

```bash
rg -n "AI lỗi|AI không làm được|đúng rule|CS workload thực tế|ước tính giảm" frontend/src
```

Expected: không có text mới khẳng định các nội dung trên trong UI.

- [ ] Chạy các gate frontend; không chạy full Python suite vì payload/backend không đổi:

```bash
cd frontend
npm run typecheck
npx vitest run test/decision-scope.test.tsx test/report-sections.test.tsx
npm run build
```

- [ ] Browser check ở `http://127.0.0.1:8765`:
  1. Chọn một tuần, nhiều tuần và toàn kỳ; title, attention và Category focus phải đổi cùng scope.
  2. Click `Xem ticket` và một Category; Ticket Explorer giữ scope chung và nhận đúng filter.
  3. Tự đổi tuần trong Ticket Explorer không làm đổi report scope.
  4. Mobile 390px không overflow; CTA dùng được bằng keyboard.

## Done When

- Phần đầu chỉ hiển thị tối đa ba cảnh báo có đường xử lý rõ ràng.
- Bảng Category hiện tại tiếp tục là nơi xem/sort/filter Category; không có thêm các ô focus riêng.
- Không thêm metric, causal claim, threshold, payload field hoặc section trùng lặp.
- Typecheck, hai test file mục tiêu và frontend build đều pass.
