# Spec — Nâng cấp tầng trình bày Dashboard để sẵn sàng cho user

> Trạng thái: **chờ duyệt**. Người viết spec: Claude. Người implement: GPT 5.6 sol (Codex).
> Đo lần cuối: 2026-07-30 trên service đang chạy `http://127.0.0.1:8765`, qua Chrome DevTools MCP.
> Phạm vi: **chỉ tầng trình bày**. Không đổi metric, không đổi payload, không đổi ranh giới PII, không đổi cách truy cập Langfuse.
> Quan hệ tài liệu: **bổ sung** `docs/SPEC-v2.md` §5; **kế tục** `plans/2026-07-30-complete-p4-ui.md` (17/17 step đã đóng). Khi mâu thuẫn với §5.3, mục §2.4 dưới đây thắng, kèm lý do đo được.
> Mục tiêu sản phẩm: sau spec này, dashboard **đủ hoàn thiện để giao cho CS lead, PO và dev dùng thật**; chỉ còn bước deploy nằm ngoài phạm vi.

---

## 0. Vấn đề

Bản đang chạy đúng về kỹ thuật: 687 test pass (exit 0); `/api/dashboard` và `/api/tickets` quét 0 hit PII (`UserID`, `TransID`, số điện thoại, email, `traceId`, `sessionId`); coverage `issue_category 90,0%` · `tpe 82,3%` · `app 79,3%` · `intent 76,8%` · `skill 50,2%`.

Nhưng nó **tối giản đến mức khó dùng**: một chart duy nhất trên trang cao 4.972px, không có tầng bậc thị giác, ba lỗi bố cục thật, và ba câu hỏi 10 giây của §5.2 không trả lời được.

| Câu hỏi §5.2 | Hiện tại | Kết luận |
|---|---|---|
| Tuần này AI xử lý bao nhiêu, **tốt lên hay xấu đi**? | `79,7%`, không có delta; section tên "WTD và tuần trước" nhưng không có tuần trước | **Trượt** |
| Có gì đang hỏng cần xử lý ngay? | `reopen 19,3%` và `>4 turn 0` cùng màu xám như mọi số khác | **Trượt** |
| Số có đáng tin không? | badge `Chất lượng DL 79%` + timestamp | Đạt |

---

## 1. Bằng chứng đã đo

### 1.1 Ba lỗi bố cục

**a. Header bảng trôi vào giữa thân bảng** — cả bảng tuần và bảng ticket.

```
.weekly-table-scroll  overflow-x:auto  ->  computed overflow = [auto, auto]  ->  LÀ scroll container
th                    position:sticky; top:var(--sticky-offset) = 133px
đo được:              th.getBoundingClientRect().top - wrap.top = 134px
```

`133px` là offset đúng cho **trang**, nhưng `th` sticky bên trong **container cuộn riêng** nên bị đẩy xuống 133px tính từ mép trên bảng. Vị trí: `static/index.html:9`, rule `html.sticky-offset-ready th{position:sticky;top:var(--sticky-offset)}`. Cùng lỗi ở `.explorer-table`. `syncStickyOffset()` (`index.html:113`) đo đúng `.topbar`; lỗi nằm ở chỗ **áp offset của trang vào phần tử sticky trong container cuộn**.

**b. Chart xu hướng bỏ trống 2/3 chiều ngang.** `renderTrend` (`index.html:70`):

- `x = 24 + index*(288/(source.length-1))` — `index` chạy trên **13 tuần kể cả 8 tuần rỗng**, chỉ 5 tuần có dữ liệu → cột dồn về 1/3 phải.
- `viewBox="0 0 320 160"` + `preserveAspectRatio="none"`, render ở `1374px` → **giãn ngang 4,3×**; hai `<text>` nhãn trục tràn hộp (`scrollWidth 179 / clientWidth 36`).

**c. Bảng tuần tràn ngang, mở đầu bằng 8 dòng rỗng.** `#weeklyTableScroll` `scrollWidth 1770 / clientWidth 1390` ở khung 1440 → cột thứ 14 bị cắt. Tám dòng "Không có dữ liệu" (04/05 → 28/06) chiếm phần đầu bảng trước dữ liệu thật.

### 1.2 Bố cục — đo ở 1440×900

Viewport thật `1440×727` (browser chrome ăn 173px).

| Chỉ số | Đo được | Vấn đề |
|---|---|---|
| Sticky topbar | `132px` = 18% chiều cao khả dụng | Hai tầng (toolbar + nav) trong một khối sticky |
| KPI grid | `342px × 4` | Mỗi thẻ lặp "WTD — không so sánh trực tiếp" + timestamp + nút "Định nghĩa" = 3 dòng nhiễu / 1 dòng số |
| `.rank-row` | `grid-template-columns: 1066px 80px 72px 150px` | Nhãn dính mép trái, số dính mép phải, **~1.000px trống ở giữa** |
| Bar segment | thang linear, max `3.911` vs min `131` | Mọi bar sau cái đầu còn 3–8px, vô nghĩa |
| Chart | 1 SVG trên trang cao `4.972px` | Không sparkline ở KPI, không nhãn trục thời gian |

### 1.3 Bố cục — đo ở 390×844 (device emulation, `isMobile+touch`)

| Chỉ số | Đo được | Vấn đề |
|---|---|---|
| Sticky topbar | `276px` = **33% chiều cao viewport** | Một phần ba màn hình điện thoại là thanh cố định |
| Tap target < 44px | **31 phần tử** | Nav 12px và các nút nhỏ khó bấm |
| Tràn ngang cấp trang | không (`docW == vw == 390`) | Đạt — giữ nguyên |
| Chiều cao trang | `6.638px` | Cuộn dài, thiếu lối nhảy nhanh |

### 1.4 Palette — chạy validator, không phán bằng mắt

`node scripts/validate_palette.js` (skill `dataviz`), surface sáng `#fcfcfb`, surface tối `#1a1a19`:

| Bộ màu | Kết quả |
|---|---|
| `#5675A8` (`--volume`) | **FAIL** chroma `0.087` < sàn `0.1` → mắt đọc thành xám |
| `#F29900` (warn theo §5.3) | **WARN** contrast `2.19` < 3:1 → không đủ cho nét vẽ mảnh |
| `#D93025` ↔ `#0F9D58` (xấu ↔ tốt) | **WARN** CVD ΔE `6.1` (deutan) — trong dải sàn 6–8, **chỉ hợp lệ khi có mã hoá phụ** (ký hiệu + nhãn chữ) |
| `#0068FF` + `#A45F00` | **PASS 5/5** (CVD ΔE 33.0, contrast ≥ 3:1) |
| `#3B86E8` + `#B07A2E` (dark) | **PASS 5/5** (band L 0.48–0.67) |

Kết luận: `--warn:#A45F00` trong code **đúng hơn** `#F29900` mà §5.3 ghi. Sửa spec theo code, không sửa code theo spec.

### 1.5 Trạng thái dữ liệu ảnh hưởng UI

`reopen_reason.status = "pending"`, `coverage: {population: 93, labeled: 0}`. Section "Lý do reopen" đã có empty state đúng chữ (`"Đang chờ taxonomy/đánh giá; chưa có nhãn do model gợi ý."`, panel `hidden=true`) — giữ hành vi, chỉ nâng hình thức.

`unmapped_tpe_codes`: 15 mã. `skill` coverage `50,2%` là thấp nhất → UI phải nói rõ khi một tab segment dựa trên chiều coverage thấp.

---

## 2. Hệ thống thiết kế

### 2.1 Định hướng

**Tactical dashboard**, chu kỳ đọc hằng tuần, ba nhóm người đọc theo §5.1 (CS lead, PO, dev). Không phải trang marketing. Định hướng: **báo cáo vận hành in được** — mật độ cao, số là nhân vật chính, màu chỉ xuất hiện khi màu mang nghĩa.

**Phần tử chữ ký** (một thứ duy nhất được phép nổi): **dải "Cần xử lý"** ngay dưới KPI — tối đa 3 dòng, mỗi dòng một vấn đề cụ thể kèm số và liên kết tới section giải thích. Nó trả lời câu hỏi §5.2 thứ hai trong một cái nhìn. Không có vấn đề nào vượt ngưỡng thì dải **biến mất hoàn toàn**, không hiện "Mọi thứ ổn".

Mọi thứ khác giữ im lặng: viền 1px, không bóng, không gradient, không animation ngoài hover 120ms.

### 2.2 Token khoảng cách

Thang 4px theo §5.3: `4 · 8 · 12 · 16 · 24 · 32`. Thêm ba biến bố cục:

```css
--gutter: 24px;          /* lề shell, giữ nguyên */
--content-max: 1120px;   /* khối chữ, rank list, diagnostic list */
--table-max: 100%;       /* bảng được phép rộng hết shell */
```

Lý do `1120px`: cột nhãn `.rank-row` hiện `1066px`; giới hạn khối đưa nhãn và cụm số về gần nhau, cắt khoảng trống ~1.000px ở §1.2.

### 2.3 Thang chữ

Một họ chữ (`system-ui`), hai vai trò theo §5.3. Bốn bậc, không thêm:

| Vai trò | Cỡ / trọng lượng / spacing | Dùng ở |
|---|---|---|
| `display` | `clamp(22px, 2.5vw, 30px)` / 750 / `-.04em` | `#dynamicTitle` |
| `metric` | `28px` / 750 / `-.03em` / `tabular-nums` | Số KPI |
| `body` | `14px` / 400–650 | Nội dung, ô bảng |
| `caption` | `12px` / 650 / `.02em` | Nhãn, eyebrow, chú thích chart |

Bỏ bậc `11px` đang dùng ở `.kpi-note`, `.axis-label`, `.navrow a` — dưới 12px là nguyên nhân chính của "khó nhìn". Mobile không nhỏ hơn 12px.

### 2.4 Màu — sửa §5.3 theo kết quả validator

| Vai trò | Sáng | Tối | Ghi chú |
|---|---|---|---|
| Accent / AI First | `#0068FF` | `#3B86E8` | Một nghĩa xuyên suốt theo §5.3 |
| Reopen (chuỗi 2) | `#A45F00` | `#B07A2E` | Thay `#F29900`: validator PASS, `#F29900` WARN contrast 2.19 |
| Volume (cột) | accent ở opacity 72% | như trên | `#5675A8` bị **bỏ khỏi vai trò phân loại** (chroma FAIL); cột volume đứng một mình trong chart riêng nên không cần màu phân loại |
| Tốt | `#0F9D58` | `#5DDB93` | **Luôn kèm ký hiệu + nhãn chữ** (CVD ΔE 6.1) |
| Xấu / cần xử lý | `#D93025` | `#FF8A80` | Như trên |
| Mực / viền / nền phụ | `#111418` / `#E3E6EA` / `#F7F8FA` | giữ nguyên | |

Ràng buộc bắt buộc: **không bao giờ mã hoá tốt/xấu bằng màu đơn độc.** Mỗi lần dùng phải kèm `▲`/`▼` + số, hoặc nhãn chữ. Đây là hệ quả trực tiếp của ΔE 6.1 ở §1.4, không phải sở thích. Tối đa 8 màu phân biệt theo §5.3 — spec này dùng 5.

---

## 3. Đặc tả từng thành phần

### 3.1 Thanh cố định

Một tầng, không hai.

- Desktop: **≤ 96px**. Hàng 1: tên trang + toggle T2–CN/T2–T6 + badge chất lượng + timestamp + nút làm mới. Hàng 2 (nav) **không sticky**, cuộn đi cùng trang.
- Mobile: **≤ 120px** (hiện 276px). Nav thành dải cuộn ngang, ẩn khi cuộn xuống, hiện lại khi cuộn lên.
- `--sticky-offset` đo từ **phần tử sticky thật sự**, không đo cả `.topbar`.
- Trong **mọi container cuộn** (`.weekly-table-scroll`, `.explorer-table`): `th { top: 0 }`. `--sticky-offset` chỉ áp cho bảng **không** nằm trong container cuộn.

### 3.2 Thẻ KPI

Bốn thẻ, mỗi thẻ **một dòng nhiễu duy nhất**:

```
┌───────────────────────────────┐
│ AI First                      │  caption
│ 79,7%   ▲ 2,3 đ so tuần trước │  metric + delta (ký hiệu, không chỉ màu)
│ ▁▂▃▅▆▇  13 tuần               │  sparkline cao 24px, cùng accent
│ 27/07–02/08 · WTD chưa đủ tuần│  caption một dòng
└───────────────────────────────┘
```

- **Delta bắt buộc**: so với **tuần hoàn chỉnh gần nhất**. Nếu thẻ đang hiển thị WTD thì delta so **cùng kỳ tuần trước** và caption ghi rõ điều đó.
- Sparkline: 13 tuần, chỉ tuần có dữ liệu, **không vẽ 0** (§5.3).
- Timestamp: **xoá khỏi từng thẻ** (đã có ở topbar).
- Nút "Định nghĩa": gộp thành **một** disclosure cho cả hàng, mở ra `<dl>` 4 định nghĩa.
- Ngưỡng lấy từ dữ liệu, không hardcode cảm tính: reopen 7 ngày > **trung vị của các tuần hoàn chỉnh có dữ liệu (`has_data == true`, `cohort_status == "complete"`) trong cửa sổ 13 tuần, cộng 5 điểm phần trăm** → cảnh báo; `gt4_turn_without_cs > 0` → cảnh báo. Dưới 3 tuần có dữ liệu thì **không** tính ngưỡng và **không** cảnh báo. Thẻ vượt ngưỡng đổi viền **và** thêm nhãn chữ.

### 3.3 Dải "Cần xử lý" (phần tử chữ ký)

Ngay dưới KPI. Tối đa 3 dòng, sort theo mức nghiêm trọng:

```
▼ Reopen 26,6% ở nhóm Thanh toán-IBFT — cao hơn trung vị 13 tuần 6,1 điểm      → Segment
▼ Khuyến mãi: 2,2% AI · 97,2% chuyển CS trên 362 ticket — gần như không phủ    → Segment
▼ 15 mã TPE chưa có trong taxonomy; 621 ticket rơi vào "Không xác định"        → Dữ liệu
```

Mỗi dòng: ký hiệu + câu tiếng Việt đầy đủ có số + liên kết tới section. Không vấn đề nào vượt ngưỡng thì **không render dải này**.

### 3.4 Bảng báo cáo tuần

- Tám tuần rỗng gộp thành **một dòng**: `8 tuần không có dữ liệu (04/05 – 28/06)`, bấm để mở.
- Cột `Tuần` ghim trái (`position:sticky; left:0`) có viền phải phân tách.
- Mặc định 8 cột; nút "Xem đủ cột" (đã có) mở 14 cột.
- Container cuộn có gợi ý: bóng mờ mép phải khi còn nội dung, xoá khi cuộn hết.
- `th { top: 0 }` — sửa lỗi §1.1a.
- Copy/CSV giữ nguyên hành vi, giữ nguyên nội dung xuất.

### 3.5 Chart xu hướng — tách hai, không dùng hai trục

Chart hiện tại vẽ cột (volume) + hai đường (tỉ lệ) trên cùng khung = **hai thang y**, lỗi chart số một theo `dataviz`. Tách:

```
Chart 1 — Volume theo tuần        cột, accent 72%, một thang, một chuỗi -> không legend
Chart 2 — AI First và Reopen (%)  hai đường, thang 0–100%, legend sát chart
                                  dùng chung trục x; nhãn tuần chỉ vẽ ở chart 2
```

- Chỉ vẽ tuần **có dữ liệu**; `index` chạy trên tập đã lọc — sửa §1.1b.
- `viewBox` theo tỉ lệ render thật, `preserveAspectRatio="xMidYMid meet"`; nét 2px, marker ≥ 8px.
- Tuần WTD: viền đứt **và** nhãn chữ "WTD".
- **Lớp hover bắt buộc**: crosshair + tooltip trên chart đường, tooltip từng cột trên chart cột; vùng bấm lớn hơn mark. Click/Enter vẫn lọc theo tuần như hiện tại.
- Nhãn trục: tối thiểu đầu–giữa–cuối trên x; 0/50/100 trên y chart 2. Không đặt số trên mọi điểm.
- Bảng tuần §3.4 là "table view" tương đương; chú thích chart phải trỏ tới nó.

### 3.6 Danh sách segment

Từ 4 cột giãn full-bleed sang **bảng thật**, giới hạn `--content-max`:

```
Nhóm vấn đề                    Ticket   %AI      %chuyển CS   Δ tuần
Thanh toán-IBFT   ███████████   3.911   94,2%    12,0%        ▲1,1
Không xác định    ██              621   64,1%    44,8%        ▼3,4
Khuyến mãi        █               362    2,2% ▼  97,2% ▼      —
```

- Cột nhãn `max-width:320px`, `text-overflow:ellipsis`, tooltip đầy đủ.
- Bar `width:200px` cố định, thang linear theo max của nhóm, **sàn hiển thị 2px** để hàng nhỏ không biến mất; khoảng cách 2px giữa bar và nền.
- Sort giảm dần theo ticket (§5.3). Thêm chế độ sort "ưu tiên cải thiện" = `volume × %chuyển CS`, đặt cạnh tab, **không** thay mặc định.
- Ô vượt ngưỡng xấu: màu **kèm** `▼`.
- Top 8 + gộp "Khác" theo §5.3; giữ nút mở rộng hiện có.
- Tab dựa trên chiều coverage thấp (`skill 50,2%`) phải hiện caption: `Chiều này phủ 50,2% ticket; phần còn lại không có dữ liệu skill.`

### 3.7 Chẩn đoán chuyển CS · Rule >4 turn · Lý do reopen

- Giữ nguyên nội dung và ngữ nghĩa. Chỉ áp `--content-max`, thang chữ mới, quy tắc màu-kèm-ký-hiệu.
- `Lý do reopen`: giữ empty state; khi `status != "ready"` thì panel vẫn `hidden` và câu trạng thái nêu rõ đang chờ gì (`labeled 0/93`).
- `gt4_turn_without_cs > 0` là nguồn cho dải "Cần xử lý" §3.3.

### 3.8 Ticket Explorer

- 11 control gom thành **3 nhóm có nhãn**: `Định danh` (Ticket ID) · `Kết quả` (Outcome, Đã chuyển CS, >4 turn) · `Phân loại` (Nhóm vấn đề, App, Nghiệp vụ, Skill, Intent, Mã TPE, Cuối tuần).
- Mỗi control cao **44px**, xếp theo `repeat(auto-fit, minmax(200px, 1fr))` — hết cảnh 11 chiều rộng lệch nhau (đo được 64→332px).
- Nút "Lọc ticket" và "Xuất CSV" cố định cuối nhóm, cùng vị trí ở mọi breakpoint (§5.3).
- Bảng kết quả: `th { top: 0 }`, cột `Ticket` ghim trái, `—` giữ nguyên cho ô rỗng.
- **Không thêm cột dữ liệu mới.** Ranh giới browser giữ nguyên: chỉ Ticket ID, không ID nội bộ.

### 3.9 Responsive

| Breakpoint | Quy tắc |
|---|---|
| ≥ 1280px | KPI 4 cột; chart 1 và 2 xếp dọc rộng hết shell; rank list `--content-max` |
| 768–1279px | KPI 2 cột; segment giữ dạng bảng, ẩn cột `Δ tuần` |
| < 768px | KPI 2 cột; sticky ≤ 120px; nav cuộn ngang; bảng cuộn ngang có gợi ý; **mọi tap target ≥ 44px** |

### 3.10 Trạng thái vận hành — điều kiện để giao cho user

Sản phẩm hoàn thiện là sản phẩm **không có trạng thái nào không được vẽ**. Bốn trạng thái phải có hình thức rõ ràng:

| Trạng thái | Nguồn | Hình thức |
|---|---|---|
| Lần đầu tải, chưa có snapshot | `/readyz` = 503 | Khối giữa trang: "Đang lấy dữ liệu lần đầu từ Langfuse. Việc này mất vài phút." Không vẽ khung rỗng, không vẽ 0. |
| Đang refresh nền, có dữ liệu cũ | `refreshing: true` | Chỉ báo nhỏ cạnh timestamp: "Đang lấy dữ liệu mới". Số vẫn hiện. Không chặn tương tác, không nhấp nháy. |
| Refresh thất bại | `last_error_code` | Dòng cạnh timestamp: "Lần cập nhật lúc HH:MM thất bại (mã X). Đang hiển thị dữ liệu lúc HH:MM." Không hiện stack trace, không hiện chi tiết nội bộ. |
| Bấm làm mới trong thời gian chờ | cooldown 429 | Nút tự vô hiệu + đếm giây còn lại. Không im lặng. |

Onboarding: nút "Cách đọc" (đã có) là tài liệu tại chỗ. Phải nêu đủ bốn định nghĩa outcome, ý nghĩa reopen, ý nghĩa badge chất lượng dữ liệu, và một câu nói rõ đây là dữ liệu **gần thời gian thực, không phải real-time**.

Ngân sách phải đạt, kiểm bằng DOM:

- `1440×900`: sticky ≤ 96px; hàng KPI + dải "Cần xử lý" nằm trọn màn đầu (`bottom < innerHeight`).
- `390×844`: sticky ≤ 120px (**hiện 276px**); tap target < 44px = **0** (hiện 31); không tràn ngang cấp trang (hiện đã đạt).

---

## 4. Ràng buộc không được phá

- Giữ 100% inline `<style>`/`<script>` — CSP sha256 ở `web.py:197`. Không asset ngoài, không thư viện chart. SVG vẽ tay.
- Không đổi công thức metric, không đổi bốn định nghĩa outcome, không đổi payload API.
- Không serialize text khách hàng, ID nội bộ, hay metadata bị chặn ra browser.
- `.env` mode `0600`, `runtime/` mode `0700`, snapshot `0600`.
- Repo đã được khởi tạo Git sau khi spec này được viết; không commit `.env`, `runtime/`, `artifacts/`, cache hoặc credential. Không tuyên bố đã verify Docker.
- Một họ chữ; tối đa 5 màu phân biệt; thang khoảng cách 4px.

---

## 5. Hợp đồng kiểm thử

Bổ sung `tests/test_frontend_contract.py` (kiểm chuỗi) và harness Node DOM (kiểm hành vi). Viết test **trước**, xác nhận RED, rồi implement.

Kiểm chuỗi:

```python
# sticky trong container cuộn — kiểm bằng tên rule, không phụ thuộc thứ tự thuộc tính CSS
assert "--table-sticky-top:0" in page          # biến riêng cho bảng trong container cuộn
assert "--sticky-offset" in page               # vẫn dùng cho bảng ngoài container cuộn
# giá trị thật kiểm ở tầng DOM (§ cuối mục này), không kiểm bằng so chuỗi CSS

# chart tách đôi, không hai trục
assert 'id="trendVolumeChart"' in page
assert 'id="trendRateChart"' in page
assert 'preserveAspectRatio="none"' not in page

# KPI có delta và sparkline, hết timestamp lặp
assert 'class="kpi-delta"' in page
assert 'class="kpi-sparkline"' in page
assert page.count("Cập nhật") <= 2

# dải cần xử lý, ký hiệu kèm màu
assert 'id="attentionStrip"' in page
assert "▲" in page and "▼" in page

# trạng thái vận hành
assert "Đang lấy dữ liệu lần đầu" in page
assert "Lần cập nhật" in page
```

Kiểm hành vi (harness Node):

- `renderTrend` với 8 tuần rỗng + 5 tuần có dữ liệu → cột đầu tiên có `x` trong 1/10 đầu chiều rộng, không phải 2/3 phải.
- `renderKpis` khi tuần trước không có dữ liệu → delta hiện `—`, không `NaN`, không `0`.
- `renderSegments` với max `3.911` và min `131` → mọi bar `width >= 2px`.
- `renderAttentionStrip` khi không vấn đề nào vượt ngưỡng → phần tử **không tồn tại** trong DOM.
- Tám tuần rỗng → đúng **một** hàng gộp trong `tbody`.
- `reopen_reason.status = "pending"` → `#reopenReasonDetails` giữ `hidden`.
- `refreshing: true` + có snapshot → số vẫn render, chỉ báo hiện.
- `last_error_code` khác null → dòng lỗi hiện, không chứa chuỗi stack.

Kiểm bằng DOM thật (Chrome DevTools MCP **có hoạt động** trong môi trường này; ghi kết quả vào report):

```js
// tại 1440x900 và emulate 390x844x3,mobile,touch
{ stickyHeight, tapTargetsUnder44, pageOverflowX, thOffsetFromWrapTop, trendFirstBarX }
```

Ngưỡng đạt: `thOffsetFromWrapTop === 0` · `tapTargetsUnder44 === 0` · `stickyHeight <= 96` (desktop) / `<= 120` (mobile) · `pageOverflowX === false`.

Palette: chạy lại `validate_palette.js` cho cặp sáng `#0068FF,#A45F00` và cặp tối `#3B86E8,#B07A2E`; dán output vào report; cả hai phải PASS 5/5.

---

## 6. Thứ tự thực hiện

Bốn lô, mỗi lô tự đứng được và phải xanh toàn bộ test trước khi qua lô sau.

1. **Lô 1 — lỗi bố cục.** `th{top:0}` trong container cuộn; chart chỉ vẽ tuần có dữ liệu và bỏ `preserveAspectRatio="none"`; gộp 8 tuần rỗng; ghim cột `Tuần`.
2. **Lô 2 — token + KPI.** Thang chữ 4 bậc; `--content-max`; palette §2.4; KPI thêm delta + sparkline, bỏ timestamp lặp, gộp nút định nghĩa.
3. **Lô 3 — segment + chart.** Bảng segment có sàn bar và ký hiệu ngưỡng; tách chart thành hai; thêm lớp hover.
4. **Lô 4 — hoàn thiện sản phẩm.** Dải "Cần xử lý"; bốn trạng thái vận hành §3.10; gom filter 3 nhóm 44px; thu sticky; kiểm lại hai viewport và ghi số đo vào report.

---

## 7. Ngoài phạm vi

- Đổi cấu trúc thông tin sang tab/route — cần sửa `SPEC-v2` §5 trước.
- Chạy pipeline gán nhãn `reopen_reason` để lấp `labeled 0/93` — việc backend.
- Bổ sung 15 mã TPE vào taxonomy — việc cấu hình; spec này chỉ **hiển thị** lỗ hổng đó ở dải "Cần xử lý".
- Deploy, image, domain, SSO — giữ theo `README.md` §"Production operating contract".
- Dark mode chưa kiểm bằng mắt trên thiết bị thật; spec chỉ pin giá trị đã qua validator.

## 8. Rủi ro

| Rủi ro | Cách chặn |
|---|---|
| Sửa CSS làm vỡ CSP hash | `web.py:197` sinh hash từ nội dung inline; chạy test deployment contract sau **mỗi** lô |
| Đổi selector làm vỡ 687 test hiện có | Không đổi `id` đang được test; thêm mới thay vì đổi tên |
| Sparkline làm trang chậm | SVG tĩnh 13 điểm, không animation, không listener trên từng điểm |
| Ngưỡng cảnh báo báo động giả | Ngưỡng tính từ trung vị 13 tuần trong dữ liệu; dải rỗng khi không có gì vượt |
| Tách chart làm mất hành vi lọc theo tuần | Giữ `data-week`, `role="button"`, `tabindex`, `aria-label` trên cột; test hành vi Enter/Click |

## 9. Tiêu chí sẵn sàng giao cho user

Đủ cả 9 mới coi là xong:

1. 687+ test pass, exit 0.
2. Ba câu hỏi §5.2 trả lời được trong 10 giây ở `1440×900`, không cần cuộn.
3. Bốn trạng thái vận hành §3.10 đều có hình thức, không trạng thái nào để trắng.
4. `thOffsetFromWrapTop === 0` ở cả hai bảng.
5. `tapTargetsUnder44 === 0` ở `390×844`; sticky ≤ 120px.
6. Không tràn ngang cấp trang ở cả hai viewport.
7. Quét PII trên `/api/dashboard` và `/api/tickets` vẫn 0 hit.
8. Validator palette PASS 5/5 cho cả sáng và tối.
9. "Cách đọc" nêu đủ bốn định nghĩa outcome, reopen, badge chất lượng, và câu "gần thời gian thực, không phải real-time".
