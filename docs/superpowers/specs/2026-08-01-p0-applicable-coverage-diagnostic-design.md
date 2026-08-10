# Gate P0 — báo cáo độ phủ theo nhóm áp dụng được

**Ngày:** 2026-08-01 · **Đo xong Bước 0:** 2026-08-01
**Trạng thái:** Đã implement, review và rerun live; legacy P0 fields và
`p0_pass` giữ nguyên.
**Người viết spec:** Claude · **Người implement:** Codex (GPT 5.6)
**Phạm vi:** Chỉ `verify-dimensions`. **Không đụng dashboard, không đụng payload, không bump version.**

**Rerun live 2026-08-02:** `verify-dimensions` trên 13 tuần + WTD xác nhận
`6.817` ticket, Category `5.782 / 6.817 = 84,82%`, TPE metadata
`5.429 / 6.817 = 79,64%`, và TPE trong nhóm áp dụng `tranxdetail`
`4.447 / 4.447 = 100%`. Category còn thiếu tập trung ở `entry_point` vắng
`767`, `resultpage` `194`, `tranxdetail` `49`, null-string `12`, nhóm hợp lệ
khác `13`. Gate cũ vẫn FAIL; diagnostic mẫu số áp dụng không được đổi
`p0_pass`. Lượt cross-tab observation chạy cùng ngày bị enrichment partial nên
TPE observation `0%` của lượt đó bị loại; không dùng nó thay số canonical trên.

---

## 1. Vấn đề

Gate P0 đang FAIL và chặn go-live:

```
coverage_issue_category = 0.848   (ngưỡng 0.90)
coverage_tpe            = 0.796   (ngưỡng 0.85)
p0_pass = false   →   go_live = BLOCKED
```

Giả thuyết ban đầu: cả hai fail vì mẫu số bị nới từ nhóm áp dụng sang toàn bộ ticket, trong khi ngưỡng `0.90`/`0.85` giữ nguyên (`2026-07-31-langfuse-only-p0-data-integrity-design.md` dòng 168: *"Thresholds remain exactly `0.90` and `0.85`"*).

**Bước 0 cho thấy TPE có nhóm áp dụng thật, nhưng cũng phát hiện phép đo chéo
ban đầu dùng TPE observation của dashboard, không phải field TPE metadata mà
gate P0 đang đếm.** Hai nguồn phải được tách rõ. Xem mục 2.

---

## 2. Bước 0 — ĐÃ ĐO

Bảng chéo `entry_point × (có Category, có TPE)`, đọc trực tiếp Langfuse, cửa
sổ 13 tuần + WTD tại fixed as-of `2026-08-01T22:19:56+07:00`, **6.788
session**. Chỉ đếm, không ticket ID, không PII. Timestamp này lấy từ chính log
tool của lượt đo gốc; không suy ra từ ngày tài liệu.

| entry_point | n | có Category | có TPE observation *(không phải gate P0)* |
|---|---:|---:|---:|
| `tranxdetail` | 4.428 | 4.379 · **98,9%** | 4.237 · **95,7%** |
| *(thiếu)* | 767 | 0 · **0,0%** | 352 · 45,9% |
| `"null"` (chuỗi) | 574 | 562 · 97,9% | 281 · 49,0% |
| `OAO` | 378 | 378 · 100% | 13 · **3,4%** |
| `resultpage` | 251 | 61 · **24,3%** | 238 · 94,8% |
| `default` | 243 | 234 · 96,3% | 172 · 70,8% |
| `spa/v2/promotion-pocket` | 50 | 50 · 100% | 0 · 0% |
| `Misscall_agent_8008` | 20 | 19 · 95,0% | 15 · 75,0% |
| `spa/v2/*` (9 loại còn lại) | 40 | ~100% | ~10% |
| còn lại (FAQ, um, paylater, …) | 37 | ~90% | ~40% |

Gộp theo phép đo dashboard/observation:

```
tranxdetail        n=4428   Category  98,9%   TPE  95,7%
không tranxdetail  n=2360   Category  58,4%   TPE  46,6%

Toàn bộ            n=6788   Category  84,8%   TPE observation  78,6%
```

`crosstab.py` tính TPE bằng `len(dimensions.tpe_signals) > 0`, lấy từ observation
`tool:get_transaction_processing_engine_data`. `verify-dimensions` lại tính
legacy `coverage_tpe` từ `input.other_info.meta["Mã lỗi TPE"]`. Vì vậy 95,7%
không được dùng làm số giải thích gate.

Chạy chính lệnh gate tại cùng fixed as-of cho kết quả canonical:

```
Toàn bộ gate TPE metadata      5.401 / 6.788 = 79,6%
tranxdetail gate TPE metadata  4.428 / 4.428 = 100,0%
```

Kết luận về mẫu số TPE vẫn đứng vững, thậm chí rõ hơn; nhưng mọi field
diagnostic P0 phải tái sử dụng đúng biến `tpe_present` của gate, không dùng
`tpe_signals` của dashboard.

### 2.1 Ràng buộc sản phẩm của PO: Category có thể vắng hợp lệ

PO nói: *"ticket không có giao dịch, Category là hoàn toàn bình thường và có thể xảy ra trong thực tế"*.

- **TPE:** dữ liệu observation xác nhận nhóm áp dụng là khái niệm thật:
  `OAO` 3,4%, `spa/v2/promotion-pocket` 0% trong khi `tranxdetail` 95,7%.
- **Category:** việc nhiều nhóm ngoài giao dịch vẫn có Category (`OAO` 100%,
  `default` 96,3%) chỉ mô tả dữ liệu hiện tại; nó **không chứng minh mọi ticket
  bắt buộc phải có Category**. Theo PO, ticket không giao dịch có thể vắng
  Category hợp lệ. Spec không được đổi phát biểu sản phẩm này thành lỗi nguồn.

### 2.2 Phân bố Category chưa ghi nhận

1.031 ticket thiếu Category, phân bố. Số này đối chiếu từ output canonical
`verify-dimensions` tại cùng fixed as-of (`6.788 - 5.757`), nên thay cho con số
1.032 làm tròn/sai lệch một ticket trong phép đo chéo ban đầu:

| Nhóm | Chưa ghi nhận | Tỷ trọng trong số chưa ghi nhận | Tỷ lệ chưa ghi nhận trong nhóm |
|---|---:|---:|---:|
| `entry_point` vắng | 767 | **74%** | **100%** |
| `resultpage` | 190 | 18% | 75,7% |
| `tranxdetail` | 49 | 5% | 1,1% |
| còn lại | 25 | 2% | — |

**767 ticket vắng `entry_point` thì cũng vắng Category đúng 100%.** Đây là dấu
hiệu hai field cùng không tới trong một khối metadata, nhưng chưa đủ để kết luận
ticket đó sai nghiệp vụ; một phần có thể là ticket vốn không áp dụng Category.
TPE observation của nhóm đó vẫn 45,9%, xác nhận nguồn observation độc lập với
khối metadata này.

`resultpage` ngược hẳn: TPE observation 94,8% nhưng Category 24,3%. Đây là nhóm
cần điều tra contract Category riêng; số đếm không tự chứng minh là lỗi.

### 2.3 Chuỗi `"null"` khác hẳn `entry_point` vắng

574 ticket có `entry_point` là chuỗi ký tự `"null"`. Nhìn qua tưởng cùng nhóm với "thiếu", nhưng:

| | Category | TPE |
|---|---:|---:|
| `"null"` (574) | 97,9% | 49,0% |
| vắng (767) | **0,0%** | 45,9% |

Hai nhóm hành xử hoàn toàn khác ở chiều Category. `"null"` = field có mặt, giá trị serialize hỏng. Vắng = cả khối metadata không tới.

**Gộp hai nhóm là xoá mất tín hiệu chẩn đoán mạnh nhất trong toàn bộ phép đo này.**

---

## 3. Kết luận: hai chỉ số fail vì hai lý do khác nhau

| Chỉ số | Giá trị | Nguyên nhân | Sửa ở đâu |
|---|---:|---|---|
| `coverage_tpe` | 79,6% | **Mẫu số.** Cùng metric gate đạt 100% trong `tranxdetail` | Báo cáo hai mẫu số — spec này |
| `coverage_issue_category` | 84,8% | Trộn ticket áp dụng và có thể không áp dụng; chưa có contract phân loại đáng tin | Chỉ báo phân bố; quyết định gate là spec riêng |

Không phát `coverage_issue_category_applicable`: chưa có rule nguồn nào phân biệt
ticket bắt buộc có Category với ticket vắng Category hợp lệ. Tự dùng
`entry_point` làm rule sẽ biến tương quan thành contract.

---

## Bước 1 — Phân biệt field vắng, chuỗi null-like và kiểu dữ liệu hỏng

**Sửa chỉ ở lớp chẩn đoán `entry_point`:** coi `"null"`, `"None"`,
`"undefined"`, `""` (sau trim) là giá trị hỏng khi phân nhóm và hiển thị —
chúng không phải entry point thật.

**Bắt buộc, và đây là điểm spec này khác bản trước:** báo cáo các trạng thái
tách biệt, không gộp:

```
entry_point_absent_count          767   # khối metadata không tới
entry_point_null_string_count     574   # field có mặt, giá trị hỏng
entry_point_invalid_type_count      0   # field có mặt nhưng JSON null/non-string
```

Không được gộp absent với literal `"null"` thành một con số `1341`. Bảng ở 2.3
chứng minh hai nhóm có hành vi Category khác nhau 98 điểm phần trăm; gộp lại là
mất khả năng chẩn đoán. JSON `null`, boolean, số, object hoặc array không phải
"chuỗi null"; chúng đi vào `entry_point_invalid_type_count`. Empty string và
các string `null`/`none`/`undefined` sau NFKC + trim + casefold đi vào
`entry_point_null_string_count`.

Không sửa `_raw_dimension_present()` và không áp normalization này vào cách tính
`issue_category_present_count`, `tpe_present_count` hay bất kỳ field P0 cũ nào.
Nếu sau này cần diagnostic null-string cho chiều metadata khác, làm bằng khoá
diagnostic riêng trong spec riêng. Giới hạn này là bắt buộc để gate cũ giữ
byte-identical; một Category nguồn có literal `"null"` hôm nay vẫn được gate cũ
xử lý đúng như trước, dù đó là hành vi cần điều tra riêng.

Test RED:
`test_absent_null_string_and_invalid_type_are_counted_separately`.

---

## Bước 2 — Thêm chỉ số độ phủ nhóm áp dụng, KHÔNG đổi gate

**Gate P0 giữ nguyên tuyệt đối:**

- Mẫu số thô toàn bộ ticket — không thu hẹp
- Ngưỡng `0.90` và `0.85` — không đổi
- `p0_pass` tính y hệt hôm nay

Lý do giữ: spec này chỉ thêm diagnostic, không có thẩm quyền đổi gate. PO đã cấm
thu hẹp mẫu số (`CLAUDE.md`: *"Không source segment, entry point, category hay
điều kiện field-present nào được thu hẹp mẫu số"*). Việc Category có thể vắng
hợp lệ cho thấy gate policy cần một quyết định sản phẩm riêng; không được lén
đổi trong một patch chẩn đoán.

**Khoá chẩn đoán mới, namespace tách rõ:**

```
applicable_population_definition       "entry_point == tranxdetail"
applicable_ticket_count                4428
applicable_tpe_present                 4428
coverage_tpe_applicable                1.000
non_applicable_ticket_count            1019    # entry_point hợp lệ, khác tranxdetail
entry_point_absent_count               767     # vắng entry_point
entry_point_null_string_count          574
entry_point_invalid_type_count           0     # present JSON null/non-string
diagnostic_uninspectable_ticket_count    0     # raw unit không normalize được
category_gap_by_entry_point            {"<absent>": 767, "<null-string>": 12, "resultpage": 190, "tranxdetail": 49, "<other-valid>": 13}
```

Sáu population count là **loại trừ nhau** và phải thỏa:

```
applicable + non_applicable + entry_point_absent + entry_point_null_string
  + entry_point_invalid_type + diagnostic_uninspectable == ticket_count
```

`1.593` trong phép đo gộp ban đầu là “field có mặt và khác tranxdetail”, nên đã
bao gồm 574 literal `"null"`. Sau khi quyết định tách null-string, số
`non_applicable` đúng là `1.593 - 574 = 1.019`; không được giữ cả hai rồi đếm
trùng. `diagnostic_uninspectable` nhận raw ticket unit giữ trong denominator
nhưng không tạo được normalized first trace; không nhét chúng vào nhóm vắng
metadata vì chưa có bằng chứng. `verify_raw_ticket_dimensions()` tính số này từ
raw denominator và số normalized session rồi truyền tường minh vào aggregate;
`aggregate_dimension_coverage()` không tự đoán từ một override không rõ nguồn.

**`coverage_issue_category_applicable` KHÔNG được phát ra.** Bước 0 chứng minh Category không có nhóm áp dụng — phát ra khoá đó là hợp thức hoá một khái niệm sai và mời người sau dùng nó làm ngưỡng.

Thay vào đó phát `category_gap_by_entry_point`: chỉ ra Category chưa ghi nhận
nằm ở nhóm nào, không dựng mẫu số thay thế hoặc tự gắn nhãn lỗi. **Không dùng
raw `sub_source` làm JSON key.** Chỉ các nhãn
cố định `tranxdetail`, `resultpage`, `<absent>`, `<null-string>`,
`<invalid-type>`, `<other-valid>` và `<uninspectable>` được phép; mọi string hợp
lệ khác được gộp vào `<other-valid>` trước privacy validation.

**Ràng buộc bắt buộc:**

1. **Không khoá nào ảnh hưởng `p0_pass`.** Test mạnh phải so toàn bộ legacy
   fields trước/sau trên cùng fixture: `ticket_count`, hai present count, hai
   coverage, hai pass flag và `p0_pass` giống hệt. Không chỉ sửa object output
   sau tính toán rồi kiểm một boolean.
2. **`entry_point_absent_count` đếm riêng, không gộp vào "không áp dụng".**
   Ticket vắng metadata chưa đủ bằng chứng để xếp vào nhóm áp dụng hay không áp
   dụng; giữ riêng để không che mất trạng thái nguồn.
   `diagnostic_uninspectable` cũng tách riêng và không được suy thành absent.
3. **`applicable_population_definition` in dạng chữ**, để người đọc JSON biết nhóm định nghĩa thế nào mà không phải đọc code.
4. Vẫn **privacy-validate** như output P0 hiện tại —
   `category_gap_by_entry_point` chỉ chứa nhãn cố định ở trên và số đếm.

---

## Bước 3 — JSON đọc ra được, và phân biệt hai loại fail

`verify-dimensions` tiếp tục in **đúng một JSON object trên stdout**. Không thêm
prose trước/sau JSON, không dùng stderr cho summary. Khối dưới đây là cách PO
diễn giải các field JSON, không phải output terminal literal. Nếu cần nhãn máy
đọc được, thêm các field enum/number đã privacy-validate vào cùng object; không
thêm một output mode mới trong spec này.

```
Độ phủ Transstatus/Step result
  Toàn bộ ticket         79,6%   (ngưỡng gate 85%)  → KHÔNG ĐẠT
  Ticket từ màn giao dịch 100,0%  (4.428 ticket)

  Chênh lệch do ticket không mở từ màn hình giao dịch: OAO 3,4%,
  các màn spa/v2 gần 0%. Transstatus không tồn tại cho những ticket đó.
  Gate vẫn tính trên toàn bộ ticket để không ai thu hẹp mẫu số cho số đẹp lên.

Độ phủ Category
  Toàn bộ ticket         84,8%   (ngưỡng gate 90%)  → KHÔNG ĐẠT

  767 ticket vắng entry_point cũng chưa ghi nhận Category.
  190 ticket resultpage chưa ghi nhận Category.
  Đây là phân bố để điều tra; chưa có contract đủ tin cậy để kết luận từng
  ticket là lỗi, vì PO xác nhận Category có thể vắng hợp lệ.
```

Đây là toàn bộ giá trị của spec: PO nhìn một lần là phân biệt được gate đỏ vì cơ học hay vì lỗi thật, và với lỗi thật thì biết đi tìm ở đâu. Hiện tại `go_live=BLOCKED` không nói được gì hành động được.

---

## Không nằm trong phạm vi

- **Không sửa ngưỡng.** Đổi ngưỡng/mẫu số Category là quyết định riêng của PO
  sau khi có contract áp dụng; spec chẩn đoán không tự quyết định.
- **Không gắn nhãn lỗi cho 767 ticket vắng metadata.** Spec chỉ định vị và báo
  cáo; điều tra tính áp dụng/nguồn là việc riêng.
- **Không điều tra `resultpage`.** Ghi nhận 190 ticket có TPE observation mà
  không có Category; nguyên nhân và tính hợp lệ chưa rõ.
- **Không đụng dashboard.** Không payload, không component, không bump `_STORAGE_VERSION`.
- **Không dùng Freshdesk.** `entry_point` nằm sẵn trong metadata trace Langfuse (`input.other_info.meta` → `sub_source`). Độc lập hoàn toàn với `2026-08-01-freshdesk-csat-integration-design.md`, **không** vi phạm contract langfuse-only.

---

## Thứ tự batch

| # | Nội dung | Test RED đầu tiên |
|---|---|---|
| **1** | Tách field vắng, null-like string và JSON null/non-string | `test_absent_null_string_and_invalid_type_are_counted_separately` |
| **2** | Khoá chẩn đoán, cách ly khỏi toàn bộ legacy P0 fields | `test_applicable_diagnostics_leave_every_legacy_p0_field_identical` |
| **3** | Một JSON object phân biệt hai loại fail | `test_single_json_report_distinguishes_denominator_gap_from_data_gap` |

Bước 0 đã xong, không còn là cổng chặn.

---

## Kiểm chứng

```bash
task_basetemp="$(mktemp -d)"; chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"

# Gate khong doi hanh vi
weekly-cs-report verify-dimensions --weeks 13 --include-current-wtd --as-of 2026-08-01T22:19:56+07:00 --require-p0; echo "exit=$?"   # van 1 nhu truoc

# Output khong lo PII
weekly-cs-report verify-dimensions --weeks 13 --include-current-wtd --as-of 2026-08-01T22:19:56+07:00 | grep -cE 'UserID|TransID|traceId|sessionId'   # phai 0
```

**Kiểm bắt buộc:** chạy trên cùng cửa sổ dữ liệu trước và sau thay đổi; toàn bộ
legacy P0 fields (`ticket_count`, present counts, coverage, pass flags,
`p0_pass`) phải **giống hệt từng chữ số**, và stdout vẫn parse được bằng đúng
một `json.loads`. Lệch một field nghĩa là đã vô tình sửa gate.

**Số neo cho test tích hợp** (cửa sổ 13 tuần + WTD, đo 2026-08-01, 6.788 session):

```
coverage_issue_category  ≈ 0.848
coverage_tpe             ≈ 0.796
applicable_ticket_count     4428
coverage_tpe_applicable     1.000
non_applicable_ticket_count 1019
entry_point_absent_count     767
entry_point_null_string_count 574
entry_point_invalid_type_count 0
diagnostic_uninspectable_ticket_count 0
```

Số sống, sẽ trôi theo tuần. Dùng làm mốc đọc, **không hardcode vào source** (`2026-07-31-langfuse-only` bất biến số 3: *"Live counts are never constants in executable source or configuration"*).

---

## Điều phải nói thẳng

1. **Hai metric TPE từng bị trộn nguồn.** 95,7% là coverage của observation
   `tpe_signals` dùng cho dashboard; 100% là coverage field metadata mà gate P0
   thực sự đếm trong `tranxdetail`. Diagnostic phải theo metric gate, nếu không
   JSON giải thích một số khác với số đang chặn go-live.

2. **Category chưa có mẫu số áp dụng đáng tin.** Dữ liệu cho thấy nhiều ticket
   ngoài giao dịch vẫn có Category, nhưng PO xác nhận Category vắng vẫn có thể
   hợp lệ. Không được biến tần suất hiện tại thành quy tắc nghiệp vụ.

3. **767 ticket vắng `entry_point` cũng vắng Category 100%.** Đây là tín hiệu
   định vị mạnh để điều tra khối metadata, không phải bằng chứng rằng cả 767
   ticket đều sai nghiệp vụ.

4. **`resultpage` 251 ticket, TPE 94,8% mà Category 24,3%.** Chưa giải thích được. Không chặn spec này, nhưng đáng một vé điều tra riêng.

5. **Spec này không gỡ được `go_live=BLOCKED`.** Bản trước nói gỡ được — sai. Nó làm rõ *tại sao* bị chặn và chia thành hai việc: một việc báo cáo (làm được ngay), một việc sửa nguồn (ở repo khác). PO quyết ngưỡng dựa trên đó.
