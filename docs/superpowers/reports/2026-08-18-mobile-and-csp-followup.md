# Đo tap target mobile (Ticket Explorer) + truy nguồn CSP `eval` — 2026-08-18

**Nhiệm vụ:** Task 12/13 của kế hoạch remediation (`docs/superpowers/plans/2026-08-18-dashboard-critique-remediation.md`), theo dõi hai mục còn treo trong
`docs/superpowers/reports/2026-08-18-stakeholder-persona-critique-report.md` — item #5 (form control nhỏ trên mobile) và item #8 ("chưa xác nhận được nguồn `eval()`").
Đây là báo cáo điều tra thuần — không sửa code, không tạo task fix nếu không có căn cứ.

**Kết luận nhanh:** Cả hai đều **không có vấn đề thật**. Tap target trong Ticket Explorer đạt chuẩn 44×44 ở mọi control người dùng thực sự bấm; 22 phần tử "dưới 44px" đo được đều là control cùng một loại (checkbox ẩn trong `<label>` 44px) không phải checkbox chọn dòng ticket như giả thuyết ban đầu. `eval()` bị CSP chặn là do chính zod tự dò khả năng JIT của môi trường — hành vi được zod tài liệu hoá, tự bắt lỗi, không ảnh hưởng chức năng.

---

## 1. Đo tap target — Ticket Explorer, mobile 390×844×3

### Môi trường

Chrome DevTools MCP, `emulate({viewport: "390x844x3,mobile,touch"})`, navigate tới `http://127.0.0.1:8765/`.

**Trở ngại phát hiện giữa chừng (không thuộc phạm vi task này):** server local ở cổng 8765 đang serve `runtime/dashboard_snapshot.json` sinh lúc `2026-08-12T05:41:13Z` (process chạy từ trước, chưa restart), snapshot này **thiếu field `status`** trong mọi phần tử `transfer_reasons.tpe[]` — field này được thêm bởi Task 1/Task 2 của chính remediation này (TPE status resolver, bump v21), đã merge vào code nhưng chưa có trong snapshot cũ. Zod `DashboardEnvelopeSchema` (`.strict()`, field `status: z.string().min(1).nullable()`) coi field bị thiếu hẳn (không phải `null`) là lỗi cấu trúc → `parseDashboardEnvelope` fail toàn bộ → UI hiện "Chưa tải được dữ liệu dashboard" và không render section nào, kể cả `#tickets`.

Không thể khởi động lại server (`kill` bị chặn bởi Auto Mode classifier của môi trường; chạy thêm instance ở cổng khác bị chính app từ chối với "dashboard runtime directory is unsafe" — lock 1-worker theo đúng thiết kế trong `CLAUDE.md`). Để đo được DOM thật của Ticket Explorer mà không sửa file nào, dùng `navigate_page(initScript=...)` để chèn một lớp vá **chỉ trong tab trình duyệt** (`window.fetch` override): với mọi response `/api/dashboard`, patch thêm `status: null` vào các phần tử `transfer_reasons.tpe[]` đang thiếu key này, rồi trả lại `Response` đã patch cho app tự parse. Đây là workaround test-only, không đụng tới file server/schema/code, không persist, biến mất khi đóng tab. Dữ liệu bên dưới (số ticket, cấu trúc bảng, cột) là dữ liệu thật của snapshot 12/08, chỉ riêng field `tpe.status` bị null hoá để vượt qua validation.

Ghi chú này nên được đưa vào tay người vận hành: **server 8765 cần được restart để hết stale-snapshot**, việc đó nằm ngoài phạm vi Task 12 (không sửa file, không restart hộ), nhưng nếu không nêu ra thì người kế tiếp gặp lại đúng lỗi "Chưa tải được dữ liệu dashboard" mà không hiểu vì sao.

### Kết quả — script đúng như brief yêu cầu

```js
Array.from(document.querySelectorAll('#tickets button, #tickets a, #tickets input, #tickets select'))
  .map(el => { const r = el.getBoundingClientRect();
    return { tag: el.tagName, text: (el.textContent||'').trim().slice(0,24),
             w: Math.round(r.width), h: Math.round(r.height) }; })
  .filter(x => x.w > 0 && x.h > 0 && (x.w < 44 || x.h < 44));
```

Trả về đúng **22 phần tử**, tất cả là `<input type="checkbox">` kích thước **13×13px**, không có `button`/`a`/`select` nào lọt vào danh sách.

Tổng số control trong `#tickets` (không lọc): **201**. Vậy 22/201 ≈ **10,9%** — gần với con số toàn trang (9%) brief cảnh báo, nhưng khớp là do cùng một nguồn, không phải trùng hợp che giấu vấn đề khác (xem dưới).

### Kiểm tra ngữ cảnh — 22 phần tử này là gì

Truy vết DOM: cả 22 checkbox đều có `id` dạng `columnOption-<field>` (`columnOption-opened_at`, `columnOption-outcome`, `columnOption-issue_category`, …) — đây là **checkbox bật/tắt cột hiển thị** trong bảng "tuỳ chỉnh cột" của Ticket Explorer, **không phải checkbox chọn dòng ticket** như giả thuyết "checkbox và link ticket dày đặc nhất ở đây" trong brief giả định. Đối chiếu trực tiếp: `#tickets table` chứa **0** checkbox — bảng ticket không có tính năng chọn dòng nào cả.

Mỗi checkbox này nằm lồng bên trong một `<label>` (không phải `for=` rời), và rect của `<label>` bao quanh là **340×44px** (đo trực tiếp bằng `getBoundingClientRect()`, ví dụ `columnOption-outcome`: label span x 25–365, checkbox glyph chỉ chiếm x 29–42 ở mép trái). Theo ngữ nghĩa HTML chuẩn, click/tap ở bất kỳ đâu trong toàn bộ vùng `<label>` sẽ toggle checkbox lồng bên trong — nên **vùng chạm thật sự là 340×44, không phải 13×13**. Phần 13×13 chỉ là kích thước hiển thị của ô vuông checkbox (glyph), không phải kích thước vùng nhận tap.

Các control còn lại đo được trong `#tickets` (mẫu, tất cả ≥44 theo cả 2 chiều):

| Loại | Ví dụ | w×h |
|---|---|---|
| Button hành động | "Tải CSV ticket" | 133×44 |
| Button filter chip | "Xoá bộ lọc" | 109×44 |
| Select dropdown | "Tuần", "Kết quả", "Mức độ hài lòng"... | 366×44 |
| Input text | "Mã ticket" | 366×44 |
| Link ticket ID | "6985766" | 61×44 |
| Link phụ | "Vì sao?" | 47×44 |
| Link icon-only | (không có text) | 44×44 |

150 thẻ `<a>` trong bảng ticket (50 dòng × 3 link/dòng: ticket ID + icon + "Vì sao?") — **không có link nào dưới 44px theo chiều cao**.

### Kết luận đầu tư 1

**Không có vi phạm tap-target thật trong Ticket Explorer.** Snippet raw trả về 22 phần tử "dưới 44px" đúng như brief cảnh báo con số page-wide có thể che giấu, nhưng khi lần tới ngữ cảnh, cả 22 đều là cùng một loại control (checkbox tuỳ chỉnh cột, lồng trong label 340×44 — vùng chạm thật đạt chuẩn), và **không tồn tại** checkbox chọn dòng nào trong bảng ticket. Mọi ticket link, button, select, input trong `#tickets` đều ≥44px cả hai chiều.

Ghi nhận nhỏ, không phải lỗi: glyph checkbox hiển thị chỉ 13×13 — về mặt thị giác hơi nhỏ so với vùng chạm 44px bao quanh, có thể khó nhìn thấy đã tick/chưa tick ở khoảng cách xa, nhưng đây là vấn đề thẩm mỹ tuỳ chọn, không phải rào cản thao tác (WCAG 2.5.5 đánh giá theo vùng phản hồi sự kiện, không theo kích thước glyph). Không tạo task fix cho việc này.

---

## 2. Truy nguồn vi phạm CSP `eval`

### Build có sourcemap

```bash
npm run build -- --sourcemap
```

Output: `src/weekly_cs_report/static/spa/assets/index-CGWa9HKi.js` + `index-CGWa9HKi.js.map` (2,215 KB map). Hash bundle **giữ nguyên** so với bản đang chạy live ở 8765 (không có thay đổi code nào giữa hai lần build) — nên vi phạm CSP quan sát được trực tiếp trên trang chạy thật và vi phạm truy vết qua sourcemap là **cùng một bundle, cùng một vị trí**.

Console thực tế khi load `http://127.0.0.1:8765/` (mobile viewport) phát đúng 1 lần:

```
issue> Content Security Policy of your site blocks the use of `eval` in JavaScript
sourceCodeLocation: {"scriptId":"13","url".../index-CGWa9HKi.js","lineNumber":8,"columnNumber":79133}
```

### Grep xác nhận tiền đề của brief

```
"Function(" trong toàn bộ bundle -> 1 lần duy nhất
"new Function"                    -> 0
"eval("                            -> 0
```

Đúng như brief mô tả: không có literal `eval(`/`new Function` — chỉ có **đúng một** lời gọi `Function(...)` (không có từ khoá `new` đứng ngay trước, gọi qua biến trung gian).

### Trace sourcemap

Lưu ý về hệ quy chiếu số dòng: DevTools Protocol báo `lineNumber` **0-based** (dòng 8 = dòng thứ 9 khi đếm 1-based), còn `source-map-js` `originalPositionFor` nhận `line` theo quy ước sourcemap **1-based**. Dùng thẳng `line: 8` (như brief viết) tra sai vị trí (rơi vào code fiber reconciliation vô hại của `react-dom-client.production.js`, không chứa `Function`/`eval` nào ở gần). Sau khi quy đổi đúng sang `line: 9`:

```
column 79133 -> node_modules/zod/v4/core/util.js:157:12, name "F"
```

Khớp chính xác vị trí char `Function(` duy nhất tìm thấy trong bundle (tính tay: dòng 9, cột 79132 0-based — lệch 1 cột do cách đếm boundary của map, cùng một điểm).

Đọc thẳng `node_modules/zod/v4/core/util.js:145-160`:

```js
export const allowsEval = /* @__PURE__*/ cached(() => {
    // Skip the probe under `jitless`: strict CSPs report the caught `new Function`
    // as a `securitypolicyviolation` even though the throw is swallowed.
    if (globalConfig.jitless) {
        return false;
    }
    if (typeof navigator !== "undefined" && navigator?.userAgent?.includes("Cloudflare")) {
        return false;
    }
    try {
        const F = Function;
        new F("");
        return true;
    }
    catch (_) {
        return false;
    }
});
```

Đây **chính là** suspect #1 mà brief xếp hạng cao nhất: zod tự dò môi trường có cho phép JIT-compile validator hay không, bằng cách thử `new Function("")` trong `try/catch`. Comment trong chính source zod xác nhận đúng hiện tượng đang quan sát: dưới CSP nghiêm ngặt, trình duyệt vẫn báo `securitypolicyviolation` dù exception đã bị `catch` nuốt.

`allowsEval` được bọc bởi `cached()` (getter chỉ chạy 1 lần, gán lại `Object.defineProperty` sau lần gọi đầu) — khớp với việc console chỉ log **đúng 1 lần** dù trang gọi `.safeParse()` rất nhiều lần. Nơi gọi: `node_modules/zod/v4/core/schemas.js:970-987` — mọi `ZodObject.safeParse()` (tức mọi schema `.strict()` trong `frontend/src/lib/dashboard-schema.ts`, dùng cho `DashboardEnvelopeSchema`, `TicketPageSchema`, v.v.) đọc `allowsEval.value` để quyết định dùng đường parse nhanh (JIT-compiled) hay đường chậm (interpreted) làm fallback.

### Có nằm trên đường tính năng đang dùng thật không

Có — không phải dead code lý thuyết. `parseDashboardEnvelope` chạy trên **mọi** lần fetch `/api/dashboard` (poll 2s/5 phút tuỳ trạng thái, theo `runtime-state.ts`), tức là probe này chắc chắn kích hoạt ngay khi trang load lần đầu — đúng như console log bắt được trong phiên đo thực tế ở mục 1.

### Kết luận đầu tư 2

**`eval()` bị CSP chặn là vô hại, không phải lỗi bảo mật hay lỗi chức năng.** Đây là cơ chế self-probe có chủ đích của thư viện zod (v4.4.3, pin trong `package.json`) để quyết định chiến lược parse nhanh/chậm, được zod tự viết trong `try/catch` và tự tài liệu hoá là sẽ gây đúng loại cảnh báo CSP này ở môi trường nghiêm ngặt. CSP đang làm đúng việc của nó (chặn `eval`); zod đang làm đúng việc của nó (bắt lỗi, rơi về interpreted parser, không throw ra ngoài, không crash app). Không cần fix.

**Có một tuỳ chọn dọn dẹp không bắt buộc** (không thực hiện trong task này, chỉ ghi lại để cân nhắc riêng): zod v4 hỗ trợ `z.config({ jitless: true })` để tắt hẳn probe này, đổi lấy việc luôn dùng đường parse interpreted (chậm hơn JIT nhưng không phát cảnh báo CSP nữa). Đây là đánh đổi hiệu năng-vs-console-sạch, nên do người sở hữu performance budget của SPA quyết định, không phải một "fix" mặc định.

---

## 3. Việc còn treo

- **Server 8765 cần restart** để hết trạng thái stale-snapshot (thiếu field `status` trong `transfer_reasons.tpe[]`, sinh trước khi Task 1/2 của remediation này merge field đó vào payload). Task 12 không tự restart (không được phép kill process đang chạy trong môi trường này, và không thuộc phạm vi "chỉ tạo report file"). Đây không phải bug code — chỉ là quy trình vận hành local chưa đồng bộ với branch. Người vận hành nên restart bằng đúng lệnh trong `CLAUDE.md`:
  ```bash
  .venv/bin/weekly-cs-dashboard --local --port 8765
  ```
- Không có việc gì mở với chính hai hạng mục điều tra (tap target, CSP eval) — cả hai đã đóng với kết luận "không có vấn đề thật".
- Docker: không được đụng tới, không xác nhận trong report này (không liên quan tới hai đầu việc trên).
