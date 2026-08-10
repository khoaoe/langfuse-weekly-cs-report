# Dashboard CS-agent — vòng 2: viết lại cho người đọc là CS

**Ngày:** 2026-08-01
**Trạng thái:** Đã implement và qua typecheck, unit, build, E2E cùng live audit.
**Người viết spec:** Claude · **Người implement:** Codex (GPT 5.6)
**Phạm vi:** Frontend thuần. Không đụng pipeline, không đụng payload, **không bump `_STORAGE_VERSION`**.

> **Steer 2026-08-03 — supersede Phần B khi mâu thuẫn:** PO xác nhận việc bỏ
> cả bảng điều kiện hệ thống và bảng ticket quá 4 lượt là xử lý quá tay. Hai
> bảng được khôi phục bằng dữ liệu sẵn có. Bảng điều kiện là vùng dành cho Dev
> nên hiển thị đúng giá trị nguồn, không map ý nghĩa:
> `Điều kiện gặp trên ticket đã chuyển CS` và `Ticket quá 4 lượt trả lời`
> (`Tổng`, `Đã chuyển CS`, `Chưa chuyển CS`). Không khôi phục panel
> `escalation_guard_blocked`, `max_replies_rule_fired`, “rule đã
> bắn”, “khoảng trống rule” hay “guard chặn”. Correction này đi cùng dashboard
> projection v13 vì cùng batch thêm `TicketRow.opened_at`; dữ liệu hai bảng
> chẩn đoán không đổi shape.

---

## 1. Bối cảnh

Vòng 1 (`2026-07-31-dashboard-usage-value-design.md` + 6 batch ngày 2026-08-01) đã sửa lỗi scope F1, bỏ điểm chất lượng tổng hợp, tách nhãn Skill. PO đọc lại bản đã ship và vẫn không hiểu nhiều chỗ.

Đây là feedback từ **người dùng thật trên sản phẩm chạy được**, không phải stress-test lý thuyết. Nó có giá trị hơn mọi suy đoán.

Người đọc chính là **CS**, không phải người xây pipeline. Nguyên tắc xuyên suốt: **câu nào không dạy người đọc một điều cụ thể thì xoá**. Không dặn người đọc đừng làm gì. Không mô tả chính giao diện đang hiển thị.

---

## 2. Phát hiện quyết định — đã đo, đừng suy diễn lại

### F1 (còn sót) — Badge độ phủ đang đo trên ba population khác nhau

Đo trực tiếp trên payload ngày 2026-08-01:

| Chỗ hiển thị | Con số | Mẫu số thật |
|---|---:|---|
| Badge `#dqBadge` "Skill: thiếu 38,7% ticket" | 38,7% | 6.663 ticket — toàn kỳ, grain T2–CN |
| Bảng Skill nếu bấm "Xem toàn kỳ" | 43,3% | 5.104 ticket — toàn kỳ, grain T2–T6 |
| Bảng Skill mặc định (sau batch 3) | **1,6%** | 935 ticket — tuần 27/07 |

Ba con số, ba mẫu số, một nhãn. Chênh **24 lần** giữa header và bảng.

`coverage` là field **top-level** của payload, tính một lần trên toàn bộ session ở grain T2–CN. Nó không theo view, không theo tuần. Batch 3 đã thống nhất scope cho segment và chẩn đoán nhưng **bỏ sót badge** — thiếu sót của vòng 1, không phải lỗi mới phát sinh.

### F2 — "thiếu 38,7% ticket" bị đọc thành "38,7% ticket không được phục vụ"

PO tự thuật: *"ở trên tôi hiểu thiếu skill để xử lý các ticket là 38.7% sao ở đây AI có xử lý AI First lại tới 77.8% (khác 100% - 38.7%)"*.

Hai đại lượng khác loại hoàn toàn:

- **AI First 77,8%** — AI có trả lời trước không. Đo *kết quả xử lý*.
- **Độ phủ skill 61,3%** — hệ thống có *ghi log* được ticket đó chạy skill nào không. Đo *độ đầy đủ của instrumentation*.

Một ticket AI xử lý trọn vẹn vẫn có thể không ghi được skill, vì phần ghi log skill mới bật gần đây. Chữ "thiếu ... ticket" gợi ý thiếu sót dịch vụ. Sai nghĩa hoàn toàn. **Chính PO hiểu nhầm** ⇒ CS chắc chắn cũng vậy.

### F3 — Thuật ngữ vận hành nội bộ rò ra giao diện

PO không giải mã được, dù chính họ là chủ sản phẩm:

| Chuỗi trên UI | PO phản hồi |
|---|---|
| "Rule giới hạn số lần trả lời đã bắn" | *"không hiểu ... rule ở đây là gì? bắn là gì?"* |
| "Khoảng trống rule là phần quá 4 turn mà rule chưa bắn" | *"cũng không hiểu"* |
| "Ticket đã ở CS khi guard chặn" | *"không rõ guard là gì?"* — và đoán **sai** nghĩa |
| "Cắt trái ngoài cửa sổ", "Bắt đầu trước cửa sổ" | *"khó hiểu, không rõ ràng"* |
| "Session sai khóa", "Trace không khóa" | *"khó hiểu"* |

Nghĩa thật của `escalation_guard_blocked` (đọc `enrichment.py:75-78`): observation `escalation_history_guard` trả `blocked: true` — **agent định chuyển ticket sang CS nhưng bị chặn vì ticket đã được chuyển CS từ trước**. Chặn chuyển trùng.

PO đoán là *"chuyển CS ngay từ đầu do guardrail"* — **ngược nghĩa**. Con số mà chủ sản phẩm đọc ra nghĩa ngược thì không dùng để ra quyết định được.

### F4 — Format không nhất quán giữa các ô cùng hàng

| Chỗ | Hiện tại | Vấn đề |
|---|---|---|
| 4 ô KPI | AI First ghi `77,8%`, ba ô kia ghi số nguyên | Không so sánh được, không rõ vì sao khác nhau |
| Bảng segment cột 2 | `3 (0,3%)` | Ngoặc đơn |
| Bảng segment cột 3 | `0 · 0%` | Dấu chấm giữa |
| Bảng segment cột 4 `Chuyển CS` | `51` | Không có tỷ trọng |
| Tên cột | "Ticket (tỷ trọng)" | Tên cột mô tả format, không mô tả dữ liệu |

Ba kiểu viết cho cùng một loại "số kèm tỷ lệ", trong cùng một bảng.

### F5 — Trục biểu đồ chia theo dữ liệu, không theo số người đọc được

Trục volume hiện `0 / 312 / 625 / 937 / 1250` — sinh từ `maxVolume/4`. PO muốn `0 / 250 / 500 / 750 / 1000`.

Chart cũng không có tooltip: muốn biết tuần 13/07 bao nhiêu ticket phải suy từ chiều cao cột.

### F6 — Nhãn sắp xếp áp sai loại dữ liệu

Explorer sinh câu `"sắp xếp theo {tên cột} {tăng dần|giảm dần}"` cho **mọi** cột, kể cả cột chữ. Ra: *"Kết quả tăng dần"*, *"Đã chuyển CS giảm dần"*, *">4 turn giảm dần"*. Vô nghĩa với dữ liệu chữ và boolean.

### F7 — Explorer thiếu filter tuần

10 dropdown nhưng **không có dropdown chọn tuần**. Tuần chỉ lọc được gián tiếp: bấm tuần trên chart, bấm ô KPI, hoặc nút nhanh "Tuần này" (thêm ở batch 5). Người mở thẳng Explorer không có đường chọn tuần.

---

## 3. Quyết định đã chốt với PO

| Vấn đề | Chốt |
|---|---|
| Badge độ phủ ở header | **Bỏ khỏi header**, đưa nội dung vào mục chất lượng dữ liệu |
| Mục "Số liệu này đáng tin tới đâu" | **Rút còn 3 dòng CS đọc được**, bỏ hết chỉ số kỹ thuật |
| Panel "rule >4 turn" và "Đã ở CS" | **Bỏ cả hai khối**, giữ ô KPI `>4 turn` (đã bấm được) |
| Định dạng 4 ô KPI | **Thống nhất: số lượng lớn + dòng phụ tỷ lệ** |
| Câu thừa | Bỏ hết |

---

## Phần A — Bỏ badge, dời thông tin về đúng chỗ

Sửa F1 + F2. Bỏ badge là **cách sửa lỗi lệch scope rẻ nhất**: không còn số ở header thì không còn gì để lệch.

**A1. Xoá `QualityBadge` khỏi `AppShell.tsx`.**

Xoá cả component và mọi thứ chỉ phục vụ nó:
- `QualityBadge` (`AppShell.tsx:55-96`)
- Prop `onOpenQuality` truyền vào `AppShell`; `qualityExpanded` vẫn cần cho `DataQualitySection` nên giữ ở `DashboardScreen`
- CSS `.quality`, `.qualityWarning` trong `dashboard.module.css`

**`selectWeakestCoverage` trong `selectors.ts` GIỮ LẠI** — đổi người dùng, không
xoá hàm. Nó thôi phục vụ badge ở header và chuyển sang phục vụ câu ở A2 trong
`DataQualitySection`. Test hiện có của selector giữ nguyên; các assertion render
badge hiện nằm trong `dashboard-screen.test.tsx`/`coverage-branches.test.tsx`
được đổi thành assertion badge không còn và câu chất lượng mới xuất hiện.

**Giữ lại** `#statusChip` và `#updatedAt` — hai thứ này nói tình trạng lần đọc, khác hẳn độ phủ.

Nav "Chất lượng dữ liệu" vẫn còn, vẫn cuộn tới mục đó. Đường vào không mất.

**A2. Mục chất lượng nói độ phủ bằng câu người đọc hiểu.**

Trong `DataQualitySection.tsx`, thay toàn bộ `#qualityGrid` bằng đúng một dòng
cho chiều yếu nhất. Copy phải dùng được với mọi dimension mà
`selectWeakestCoverage()` có thể trả về, không giả dimension đó luôn là Skill:

```
Skill: 61% ticket có dữ liệu Skill để phân nhóm. 39% còn lại không lọc theo
Skill được — đây là độ đầy đủ dữ liệu, không phải tỷ lệ ticket không được xử lý.
```

Ba điều bắt buộc trong câu này:
1. Nói **tỷ lệ ghi được**, không phải "thiếu" — bỏ hàm ý thiếu sót dịch vụ
2. Nói **hệ quả cụ thể**: `không lọc theo {label} được`
3. Nói **thẳng điều không phải**: "không phải ticket không được xử lý" — chặn đúng cách hiểu sai PO đã mắc

Template bắt buộc:

```
{Label}: {recorded}% ticket có dữ liệu {Label} để phân nhóm. {missing}% còn lại
không lọc theo {Label} được — đây là độ đầy đủ dữ liệu, không phải tỷ lệ ticket
không được xử lý.
```

Không nêu nguyên nhân lịch sử như “chạy trước khi hệ thống bắt đầu ghi” nếu
payload không chứng minh nguyên nhân đó cho dimension đang hiển thị.

Chiều nào `coverage >= 0.8` thì không hiện dòng nào.
Nếu mọi coverage đều đạt và không có tuần trống, mục chất lượng chỉ còn đúng
một dòng freshness; không thêm câu đệm để đủ số dòng.

**A3. Ghi rõ mẫu số ngay trong câu.**

`coverage` là toàn kỳ. Sau khi cả trang chuyển sang "tuần đang chọn", phải nói ra:

```
Tính trên toàn bộ 6.663 ticket trong 13 tuần, không phải riêng tuần đang xem.
```

Đây là câu **được phép giữ** vì nó ngăn đúng lỗi lệch scope. Khác với câu bị bỏ ở phần D — câu đó mô tả giao diện, câu này nói mẫu số.

Không hard-code `6.663` hoặc `13`. Vì `coverage` top-level được tính trên toàn bộ
population T2–CN, frontend lấy mẫu số từ
`snapshot.views.mon_sun.totals.eligible_ticket_count`; số tuần là số dòng
`has_data=true` trong `snapshot.views.mon_sun.weekly`. Không dùng active view/tuần
đang chọn cho câu này. Test fixture phải cố ý cho `mon_fri` và `mon_sun` khác nhau
để khóa đúng nguồn.

---

## Phần B — Bỏ hai khối chẩn đoán không giải mã được

Sửa F3.

**B1. Xoá nội dung hiển thị của `#ruleGt4Panel`, `#ruleScope`, `#ruleGt4Alert` khỏi `GuardrailZone`.**

Trong `TransferDiagnostics.tsx`, xoá:
- `<dl id="ruleGt4Panel">` — "Ticket quá 4 turn", "Rule giới hạn số lần trả lời đã bắn", "Khoảng trống rule..."
- `<p id="ruleScope">` — "Rule bắn 87 lần, trong khi 118 ticket đã vượt 4 turn..."
- Nút `#ruleGt4Alert` — **trùng chức năng** với ô KPI `>4 turn` đã bấm được từ batch 4

**Xoá cả bảng Guardrail/rule khỏi giao diện CS-facing.** Các mã
`missing_transaction_id`, `off_topic`, `cs_escalation`, ... là giá trị nguồn
thật nhưng vẫn là taxonomy nội bộ; tính "thật" không làm chúng dễ hiểu hay hành
động được với CS/PO. Payload giữ nguyên cho backend/dev diagnostics, nhưng
không render, không đưa vào narrative và không có cột Explorer/export.

Hệ quả dây chuyền: prop `rule` và `onShowStuckTickets` của `TransferDiagnostics` không còn ai dùng ⇒ xoá khỏi signature. `BelowFold.tsx` thôi tính biến `rule` (dòng 727-736) và thôi truyền hai prop đó. `DashboardScreen.tsx` **giữ** `showStuckTickets` vì ô KPI vẫn gọi.

Trước khi xoá nút cũ, thêm regression test bấm ô KPI `>4 turn` và chứng minh
Explorer nhận đúng filter `gt4_turn=true`, `transferred=false`. Test xoá panel
không được thay thế test đường điều tra còn lại này.

`AGENTS.md` yêu cầu giữ compatibility DOM IDs trong một release. Vì vậy trong
release này đặt các anchor rỗng `hidden aria-hidden="true"` mang đúng các ID cũ
(`ruleGt4Panel`, `ruleScope`, `ruleGt4Alert`); không còn text, button role hoặc
khả năng focus. Khóa hành vi này bằng Vitest của SPA. Không sửa
`tests/test_frontend_contract.py`: file đó kiểm `static/index.html` legacy và
legacy phải giữ byte-identical. Release sau mới xóa hẳn ID bằng một quyết định
riêng.

**B2. Xoá `AlreadyCsZone` khỏi giao diện (`#escalationPanel` chỉ còn anchor ẩn một release).**

Xoá cả khối "Đã ở CS". Lý do không phải vì chữ xấu mà vì **PO đọc ra nghĩa ngược**. Viết lại cũng chỉ ra một câu dài mà không ai hành động được từ nó.

`escalation_guard_blocked` vẫn còn trong payload, không đổi. Cần thì dựng lại từ dữ liệu có sẵn.

Nhãn `Đã ở CS` còn xuất hiện trong Ticket Explorer cho cùng field và gây đúng
cách hiểu sai đó. Đổi nhãn cột/filter presentation-only thành
`Chặn chuyển CS trùng`; giữ nguyên key, value, filter, CSV grain và payload.

Sửa luôn predicate empty-state: sau khi `AlreadyCsZone` và bảng Guardrail bị bỏ,
riêng `escalation_guard_blocked.count > 0` hoặc `transfer.guardrail.length > 0`
**không** còn được coi là một tín hiệu đang hiển thị. Nếu không còn TPE nào,
render empty state bình thường;
không để vùng chẩn đoán trắng. `escalationPanel` tuân theo anchor ẩn như B1.

**B3. Bỏ câu mở đầu mục chẩn đoán.**

```
Bỏ: "Một ticket có thể mang nhiều tín hiệu cùng lúc, nên các con số dưới đây
     chồng lấn và không cộng lại thành tổng chuyển CS. Đây là tín hiệu quan
     sát được, không phải nguyên nhân đã chứng minh."
```

Hai câu dặn người đọc đừng kết luận. Không nói con số nào. Giữ `#transferScope`
(mẫu số + tuần) vì đó là dữ kiện. Ranh giới observation-vs-causality được giữ
bằng title và nhãn nhất quán `Tín hiệu chuyển CS`; không đổi bất kỳ label nào
thành “nguyên nhân”, và không thêm lại một disclaimer dài khác.

**B4. Không để thuật ngữ Guardrail/rule rò ở chỗ khác, ngoại trừ bảng Dev.**

- `selectTransferSignals()` chỉ đưa TPE signal vào narrative; không đưa raw
  guardrail codes.
- Xoá `guardrail_rule` khỏi allowlist cột Ticket Explorer. Dữ liệu vẫn ở payload
  nhưng không render/export; localStorage cũ tự bị allowlist loại.
- Help/degraded copy dùng từ người đọc hiểu được ("trạng thái giao dịch",
  "dữ liệu phân nhóm") và không còn `Guardrail`, `rule`, raw rule code.
- Ngoại lệ duy nhất là `Điều kiện gặp trên ticket đã chuyển CS`: cột `Giá trị
  nguồn` phải giữ nguyên raw rule code vì Dev dùng để debug.
- Heading mục là `Tín hiệu chuyển CS`, không còn `rule >4 turn`.
- Regression test chứng minh các cụm diễn giải mơ hồ `rule đã bắn`, `guard
  chặn`, `khoảng trống rule` không xuất hiện; raw rule code chỉ được phép trong
  đúng bảng Dev nói trên.

---

## Phần C — Thống nhất cách viết số

Sửa F4.

**C1. Bốn ô KPI cùng một khuôn: số lượng lớn, tỷ lệ ở dòng phụ.**

Trong `selectors.ts` `selectLedger()`:

| Ô | Value (lớn) | Support (nhỏ) |
|---|---|---|
| AI First | `727` | `77,8% trong 935 ticket tuần này` |
| Tổng chuyển CS | `208` | `22,2% trong 935 ticket tuần này` |
| Reopen sau AI First | `152` | `20,9% trong 727 ticket AI First` |
| >4 turn chưa chuyển CS | `0` | *(không có dòng phụ khi bằng 0 — giữ quy tắc batch 1)* |

Vì sao chọn số lượng làm chính: ba trong bốn ô vốn là số đếm; ép cả bốn về tỷ lệ thì "Tổng chuyển CS 22,2%" mất con số CS cần khi phân việc. Ngược lại, đưa cả bốn về số đếm giữ được cả hai — tỷ lệ vẫn nằm ngay dưới.

Mẫu số phải ghi rõ, và **khác nhau giữa các ô là bình thường** — reopen tính trên ticket AI First, không phải tổng ticket. Ghi ra thì người đọc không cộng nhầm.

**C2. Bảng segment: một kiểu viết cho mọi cột số.**

| Cột | Hiện | Sau |
|---|---|---|
| Tiêu đề cột 2 | `Ticket (tỷ trọng)` | `Ticket` |
| Ô cột 2 | `3 (0,3%)` | `3 · 0,3%` |
| Ô cột 3 `AI First` | `0 · 0%` | `0 · 0%` (giữ) |
| Ô cột 4 `Chuyển CS` | `51` | `51 · 7,5%` |
| Ô cột 5 `Reopen` | `130` | `130 · 19,2%` |

Quy tắc: **`{số} · {tỷ lệ}`**, dấu `·` ở mọi nơi, không dùng ngoặc đơn.

Mẫu số của từng cột ghi trong caption bảng, không ghi lặp trong từng ô:
```
Ticket: tỷ trọng trong tuần. AI First, Chuyển CS, Reopen: tỷ lệ trong chính nhóm đó.
```

**C3. Tỷ lệ 0 và 100 vẫn không có số thập phân.** Quy tắc `formatRate` từ batch 1 giữ nguyên — `0%`, `100%`, còn lại một chữ số thập phân.

---

## Phần D — Xoá câu không dạy được gì

Xoá đúng những chuỗi này:

| File | Chuỗi bị xoá |
|---|---|
| `BelowFold.tsx` | "Phân nhóm trực tiếp theo Category, App, ... **không tự gộp hoặc diễn giải lại.**" — xoá cả câu |
| `TicketExplorer.tsx` | "180 giá trị intent, nhiều biến thể viết khác nhau của cùng một ý." |
| `DataQualitySection.tsx` | "Phiên hợp lệ về cấu trúc: 100%. Cổng backend chỉ chặn khi lỗi cấu trúc vượt 5%." |
| `DataQualitySection.tsx` | Toàn bộ `QUALITY_FIELDS`: "Mở vào cuối tuần", "Cắt trái ngoài cửa sổ", "Bắt đầu trước cửa sổ", "Session sai khóa", "Trace không khóa" |
| `DataQualitySection.tsx` | `#gateGrid`: "Không có turn đầu: 747 · Hợp lệ: 6.012" |
| `DataQualitySection.tsx` | Cả khối `#stepResultCoveragePanel` "Độ phủ Step result" |
| `DataQualitySection.tsx` | "Survey khách hàng: không có trong Langfuse; cần nguồn Freshdesk/CSAT riêng..." — **sẽ sai** sau khi có CSAT; xoá luôn |

**Mục chất lượng còn tối đa 3 dòng:**

```
Cập nhật 16:37 31/7, cách đây 4 phút.

{Label}: {recorded}% ticket có dữ liệu {Label} để phân nhóm. {missing}% còn lại
không lọc theo {Label} được — đây là độ đầy đủ dữ liệu, không phải tỷ lệ ticket
không được xử lý. Tính trên toàn bộ {ticket_count} ticket trong {week_count}
tuần.

8 trong 13 tuần không có ticket nào. Các tuần đó để trống, không phải bằng 0.
```

Dòng 3 giữ vì nó chặn đúng một lỗi đọc thật (nhìn tuần trống tưởng volume tụt). Viết lại bỏ chữ "cửa sổ".

Dòng coverage là conditional theo A2 và dùng chiều yếu nhất thực tế, không mặc
định là Skill. Khi mọi coverage `>= 0.8`, mục này có đúng 2
dòng (freshness và tuần trống), không dựng dòng rỗng để đủ ba.

Các ID `qualityGrid`, `gateGrid`, `stepResultCoveragePanel` cũng giữ dưới dạng
anchor rỗng `hidden aria-hidden="true"` trong một release; cập nhật contract test
để không còn đòi nội dung cũ.

Hệ quả: prop `stepResultMissing` của `DataQualitySection` không còn ai dùng ⇒ xoá khỏi signature và khỏi `BelowFold.tsx`.

---

## Phần E — Biểu đồ

Sửa F5.

**E1. Trục chia theo số tròn.**

File mới `frontend/src/lib/chart-scale.ts`. Thuật toán "nice number": chọn bước từ `{1, 2, 2.5, 5, 10} × 10^n` sao cho ra 4–5 vạch phủ hết `maxVolume`.

```
maxVolume = 1180  →  bước 250  →  0 / 250 / 500 / 750 / 1000 / 1250
maxVolume = 47    →  bước 10   →  0 / 10 / 20 / 30 / 40 / 50
maxVolume = 3     →  bước 1    →  0 / 1 / 2 / 3
maxVolume = 0     →  bước 1    →  0 / 1     (không chia cho 0)
```

Hàm thuần tuý, dễ test ⇒ test riêng cho đúng bốn mốc trên. Thay `ticks()` trong `BelowFold.tsx`.

Acceptance là “mọi tick là số tròn và tick cuối phủ `maxVolume`”. Ví dụ PO nêu
`0 / 250 / 500 / 750 / 1000` là nhịp mong muốn; với dữ liệu 1.180, trục đúng
phải thêm `1.250`, không được cắt mất cột cao nhất.

Trục tỷ lệ giữ nguyên `0/25/50/75/100%` — vốn đã tròn.

**E2. Tooltip khi hover cột và điểm.**

Đã có sẵn `.weekTarget`/`.weekHit` phủ toàn bộ chiều rộng mỗi tuần (`BelowFold.tsx:219-240`) — dùng lại đúng vùng đó, **không thêm vùng bắt sự kiện mới**.

Nội dung:

```
Biểu đồ volume:     Tuần 13/07–19/07
                    Tổng 1.180 ticket
                    AI First 918 ticket

Biểu đồ tỷ lệ:      Tuần 13/07–19/07
                    AI First 77,8%
                    Reopen sau AI First 20,9%
```

Ràng buộc:
- `<title>` trong SVG **không đủ** — chậm hiện và không xuống dòng được. Dựng `<div>` định vị tuyệt đối theo con trỏ.
- Một state tooltip dùng chung cho pointer target SVG và nút `.weekSelector`;
  `.weekTarget` vẫn `aria-hidden`/không focus, còn bàn phím focus nút ngoài SVG
  thì mở cùng nội dung tooltip tương ứng
- Tooltip là DOM text có `role="tooltip"`; nút `.weekSelector` đang focus trỏ
  tới nó bằng `aria-describedby`, để screen reader nhận cùng số liệu như người
  dùng hover/focus bằng mắt
- Không chặn click chọn tuần đang có
- Không tràn khỏi viewport ở 390px — lật sang trái khi gần mép phải

---

## Phần F — Ticket Explorer

**F1. Thêm dropdown chọn tuần** — đặt **đầu tiên** trong `#ticketFilters`, trước "Mã ticket".

Options: mọi tuần có `has_data`, nhãn `formatWeekRange`, mới nhất trên cùng. Option rỗng = "Tất cả tuần".

Đây là filter hay dùng nhất mà lại đang thiếu; đặt đầu tiên đúng thứ tự người nghĩ.

**F2. Bỏ câu mô tả sắp xếp.**

Xoá vế `· sắp xếp toàn bộ kết quả theo {cột} {tăng dần|giảm dần}` khỏi `#tickets-caption`. Giữ `{n} ticket khớp bộ lọc`.

Lý do: `aria-sort` trên từng header đã mang thông tin này cho screen reader, mũi tên đã mang cho người nhìn. Câu văn chỉ thêm chỗ sai — và đang sai thật với cột chữ.

Áp dụng **cùng cách** cho `#segmentCaption` và caption bảng TPE: bỏ vế "Đang sắp xếp theo ... tăng/giảm dần".

**F3. Sửa ô Intent lệch hàng.**

Batch 5 đổi `<label>` bọc thành `<div>` + `<label htmlFor>` và thêm `<span>` hint bên dưới ⇒ ô này cao hơn các ô khác, lệch lưới.

Sửa: bỏ `<span>` hint (đã nằm ở phần D), trả về `<label>` bọc như các ô còn lại, giữ `<input list=...>` và `<datalist>`.

Sau khi bỏ hint, kiểm mọi ô trong `#ticketFilters` cao bằng nhau ở 1440px và 390px.

---

## Thứ tự batch

TDD bắt buộc: viết test → RED → implement → GREEN → chạy full gate.

| # | Nội dung | Test RED đầu tiên |
|---|---|---|
| **1** | **A1–A3 + D** bỏ badge và thay toàn bộ quality section trong cùng batch | thêm case `header does not render a coverage number` và quality tối đa 3 dòng |
| **2** | **B1–B4** bỏ rule/Guardrail/Already-CS khỏi UI, giữ KPI drilldown | test panel/jargon biến mất **và** KPI vẫn drill down đúng |
| **3** | **C1–C2** thống nhất định dạng số | `test_all_four_ledger_cells_lead_with_a_count` |
| **4** | **E1** trục tròn | tạo `frontend/test/chart-scale.test.ts`; tick cuối phải phủ max |
| **5** | **E2** tooltip pointer + keyboard | interaction case trong `trend-chart.test.tsx` |
| **6** | **F1–F3** Explorer | `week filter is the first control`; không giả định có file `ticket-explorer.test.tsx` |
| **7** | **A–F** stress-test toàn bộ feedback trên UI thật | matrix automated + browser; defect mới phải RED trước |

Batch 1–4 độc lập hoàn toàn, ship riêng được. Batch 5 nhiều interaction mới
nhất. Batch 6 có một phần là sửa lỗi do batch 5 vòng trước gây ra.

---

## File chính

| File | Việc |
|---|---|
| `frontend/src/components/AppShell.tsx` | A1 xoá badge |
| `frontend/src/components/DataQualitySection.tsx` | A2, A3, D — viết lại còn 3 dòng |
| `frontend/src/components/TransferDiagnostics.tsx` | B1–B4 |
| `frontend/src/lib/selectors.ts` | C1 ledger; **giữ** `selectWeakestCoverage` cho A2; narrative chỉ giữ TPE signal |
| `frontend/src/components/BelowFold.tsx` | C2 bảng segment; D; E1, E2; bỏ biến `rule` |
| `frontend/src/lib/chart-scale.ts` | **Mới** — E1 thuật toán trục tròn |
| `frontend/src/components/TicketExplorer.tsx` | F1, F2, F3 |
| `frontend/src/lib/ticket-columns.ts` | B2 đổi nhãn escalation; B4 bỏ cột raw guardrail khỏi UI/export |
| `frontend/src/components/dashboard.module.css` | Xoá `.quality*`; CSS tooltip |
| `DESIGN.md`, `docs/SPEC-v2.md §5` | Cập nhật copy cố định cùng commit |

---

## Kiểm chứng

```bash
npm run test:unit && npm run typecheck && npm run build

task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"

npm run test:e2e
```

`npm run test:e2e` dùng server cô lập `127.0.0.1:18765`; không đổi sang `8765`.
Nếu chạy smoke với dữ liệu local thật, phải tự start
`.venv/bin/weekly-cs-dashboard --local --port 8765`, chờ `/api/dashboard` trả
`200`, chạy PII grep bắt buộc, rồi dừng đúng PID vừa start. Không curl mù vào một
process 8765 có sẵn.

**Chrome DevTools MCP** (hoạt động trong môi trường này — dùng, đừng ghi "không kiểm chứng được"):

- Emulate `390x844x3,mobile,touch` và `1440x900`
- `evaluate_script` đo: chiều cao trang (mục tiêu **< 3.000px**, hiện ~5.200px), mọi ô trong `#ticketFilters` cao bằng nhau, tap target ≥ 44px, không tràn ngang
- **Hồi quy F1:** không còn phần tử nào trong `<header>` chứa `%` của coverage
- Tooltip: hover cột tuần bất kỳ, đọc nội dung, kiểm không tràn viewport ở 390px

**Kiểm bằng mắt CS:** đọc từng chuỗi đã sửa như người chưa từng xây pipeline. Không hiểu thì xoá, không phải viết lại dài hơn.

---

## Điều phải nói thẳng

1. **Bỏ badge là sửa lỗi, không phải giảm tính năng.** Nó đang hiển thị 38,7% trong khi bảng ngay dưới nói 1,6% cho cùng một khái niệm. Một badge sai còn tệ hơn không có badge.

2. **Vòng 1 sửa F1 chưa hết.** Batch 3 thống nhất scope cho segment và chẩn đoán nhưng bỏ sót `coverage` vì nó là field top-level, không nằm trong `view`. Bài học: khi thống nhất scope, phải liệt kê **mọi** chỗ hiển thị số, kể cả header.

3. **"Đã ở CS" bị xoá vì PO đọc ra nghĩa ngược, không phải vì chữ xấu.** Khi chủ sản phẩm hiểu ngược một metric, viết lại chỉ ra câu dài hơn. Bỏ đi; cần thì dựng lại từ payload vẫn còn nguyên.

4. **Phần E nhiều code mới nhất.** Tooltip cần định vị theo con trỏ, xử lý bàn phím, chặn tràn viewport. Nếu gấp thì E1 (trục tròn) ship riêng được, E2 để sau.

5. **Spec này không đụng backend.** Không đổi payload, không bump version, không chạm pipeline. Toàn bộ dữ liệu cần đã có trong payload hiện tại. Nếu Codex thấy cần đổi payload thì **dừng và hỏi** — gần như chắc chắn là hiểu nhầm.

6. **Câu về survey khách hàng phải xoá ngay ở vòng này**, vì spec CSAT Freshdesk (`2026-08-01-freshdesk-csat-integration-design.md`) sẽ làm nó sai.
