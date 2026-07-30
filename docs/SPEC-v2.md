# Spec v2 — Langfuse Weekly CS Dashboard

> Trạng thái: **đã chốt, sẵn sàng implement**. Người viết spec: Claude. Người implement: GPT 5.6 sol.
> Đo lần cuối: 2026-07-29, dữ liệu thật từ `https://langfuse.zalopay.vn`, API read-only.
> Tài liệu này **thay thế** mọi mô tả metric trong `README.md` khi có mâu thuẫn.

---

## 0. Context

Dashboard hiện tại đúng về kỹ thuật (323 test pass, không rò PII) nhưng **sai về sản phẩm**:

- Hai mục phân loại quan trọng nhất (`Theo business`, `Theo TPE`) đọc sai nguồn dữ liệu → "Khác" 46%, TPE unknown 70,6%.
- Phạm vi ticket hẹp hơn thực tế ~35% → số không khớp báo cáo tay CS đang dùng.
- Nhiều trường giá trị cao có sẵn trong Langfuse nhưng chưa dùng (intent, skills, guardrail rule, escalation guard).

CS/PO không thể tin một dashboard cho ra con số khác sheet của chính họ. Spec này sửa gốc: đổi nguồn dữ liệu, mở phạm vi ticket, thêm chiều phân tích, dựng lại UI theo hướng "Weekly Report first".

---

## 1. Bằng chứng đã đo

Mọi số dưới đây đo trực tiếp trên API, không suy luận.

### 1.1 Nguồn dữ liệu thật của trace

`GET /api/public/traces?fields=core,io` trả `input.other_info.meta` — object phẳng ~30 key do Freshdesk đẩy sang:

```
input.other_info.meta = {
  "App": "241 - Chuyển Tiền ATM",
  "Product Code": "TF007 - IBFT money transfer trong ZaloPay App",
  "Mã lỗi TPE": "-383 Đang xử lý",
  "Step result": "-1|20|700212|Chuyển tiền về thẻ ATM vượt hạn mức...",
  "Kênh thanh toán": "38 - TK Zalo Pay",
  "Bank Code": "ZPMB - MBBank",
  "KYC level": "3", "Hạng thành viên": "Thành viên",
  "Platform": "ZPA", "OS": "IOS",
  "Nguồn submit ticket": "Chatbot",
  "Thông tin thêm": { "category": "Thanh toán-IBFT", "sub_source": "tranxdetail" },
  ...  // + field PII: UserID, App user, TransID, Số điện thoại người dùng
}
```

### 1.2 Hai lỗi phân loại — xác nhận đúng cả hai

| | Hiện tại | Vấn đề đo được |
|---|---|---|
| **Business** | `categories.py:165` `classify_business()` match keyword trên `other_info.title` + whitelist meta key `["category","type","usecase","domain",…]` | Whitelist **không khớp key nào có thật**. Meta dùng `App`, `Product Code`, `Thông tin thêm.category`. Duy nhất `type` khớp nhưng giá trị là `public`/`private`. → fallback `other` = 572/1243 |
| **TPE** | `categories.py:217` `classify_tpe()` đọc `observation.output.result.transstatus` của span `tool:get_transaction_processing_engine_data` | Chỉ chạy trên ticket có transfer **và** có gọi tool đó → unknown **877/1243 = 70,6%**. `meta["Mã lỗi TPE"]` có sẵn trên **86%** trace đầu, không cần observation |

**Đo lại TPE bằng meta** (7 ngày, 1.415 ticket trace-đầu): 183 không có field (12,9%); map theo `taxonomy.v1.json` **1.149 = 81,2%**.

Bug parse phải sửa: `Step result` dạng `-1|20|700212|<mô tả>`. Taxonomy map `-244` với step `700212`/`212010`/`210808` — **segment thứ 3**, không phải segment đầu. Lấy sai segment biến 50 ticket `(-244, "-1")` thành unmapped. Sửa xong coverage > 90%.

Mã TPE có trong prod, **thiếu trong taxonomy.v1**: `-217` (85/14d), `-380` (89), `-993`, `-268`, `-369`, `-1442`, `-333`, `-367`.

### 1.3 Ba nguồn dữ liệu giá trị cao chưa dùng

`GET /api/public/observations?name=<name>&fromStartTime=…` — bulk theo tên, có `traceId`, không cần gọi từng trace:

| Observation | Field | Đo 3 ngày |
|---|---|---|
| `route` (GENERATION) | `metadata.intent` | ~100 intent: `interbank-fund-transfer_recovery` 234, `_dispute` 44, `_issue` 43, `refund_request` 22, `complaint_about_processing_time` 20, `transaction_reversal_fraud` 15… |
| `execute` (SPAN) | `metadata.skills_used` | `customer-service/interbank-fund-transfer` 645, `/topup` 132, `/withdraw` 108 — "nghiệp vụ" chính xác |
| `input_guardrail`, `skill_guardrail_checked` | `output.rule` | `missing_transaction_id` 71, `cs_escalation` 49, `empty_message_marker` 12, `max_replies_exceeded` 9, `prompt_injection_llm` 4, **`off_topic` 4** |
| `escalation_history_guard` | `output.blocked` | true 114/878 = 13% — ticket đã ở CS nên AI im lặng |

`off_topic` **không có** trong `taxonomy.v1.json.guardrail.allowed_values` → đang bị nuốt thành `unknown`.

Bỏ vì vô dụng: `metadata.confidence` luôn = 1; `trace.latency` và `trace.totalCost` luôn = -1.
`trace.scores` = **rỗng trên toàn bộ 5.062 ticket** → không lấy được Survey từ Langfuse (§6).

### 1.4 Phạm vi ticket đang hẹp hơn thực tế ~35%

1. **Cohort T2–T6 loại toàn bộ ticket cuối tuần: 23,4%** — 28 ngày: Sat 767 + Sun 642 / 6.028 session. `pipeline.py:147`.
2. **687/6.105 session (11,3%) không có trace `turn == 0`** — `turn` là chỉ số message trong thread Freshdesk (max quan sát = 27), không phải chỉ số tuần tự của trace. `pipeline.py:138` và `classification.py:206` bắt buộc `turn == 0` nên đẩy hết nhóm này vào `left_censored` (693 trong snapshot). Turn nhỏ nhất của nhóm: 1 (337), 2 (114), 3 (116)…

Không phải lỗi cửa sổ thời gian: Langfuse **không có trace nào trước 2026-06-29** (May 0, Jun 1–15: 0, Jun 15–30: 1, Jul: 9.114). 8/12 tuần trong cửa sổ hiện tại rỗng thật.

### 1.5 "AI cover" — số liệu bác lại cách hiểu

Bạn mô tả: *"AI cover nghĩa là có CS-agent trả lời, trong các turn sau thì có chuyển CS"*. Đo lại bằng chính định nghĩa đó, cohort T2–CN, gồm cuối tuần, không đòi `turn == 0`:

| Tuần | AI first | AI **không** chuyển CS | AI **rồi** chuyển CS | Chuyển CS ngay | Reopen | Tỷ lệ reopen |
|---|---|---|---|---|---|---|
| 01/07–05/07 | 636 | **582** | **54** | 298 | 183 | 28,8% |
| 06/07–12/07 | 870 | **822** | **48** | 309 | 144 | 16,6% |
| 13/07–19/07 | 1.225 | **1.114** | **111** | 456 | 326 | 26,6% |
| 20/07–26/07 | 1.374 | **1.220** | **154** | 348 | 360 | 26,2% |

Sheet của bạn:

| Tuần | Tổng AI first | AI cover | Chuyển CS | Reopen | Tỷ lệ reopen |
|---|---|---|---|---|---|
| 01/07–05/07 | 610 | **594** | **16** | 165 | 27,0% |
| 06/07–12/07 | 1.167 | **1.129** | **38** | 179 | 15,3% |
| 13/07–19/07 | 1.453 | **1.350** | **103** | 391 | 26,9% |
| 20/07–26/07 | 1.298 | **1.189** | **109** | 345 | 26,6% |

Đặt cạnh nhau:

- Cột **"AI cover"** của sheet (594 / 1.129 / 1.350 / 1.189) bám sát cột **AI không chuyển CS** (582 / 822 / 1.114 / 1.220).
- Cột **"Chuyển CS"** của sheet (16 / 38 / 103 / 109) bám sát cột **AI rồi chuyển CS** (54 / 48 / 111 / 154).

Nếu "AI cover" thật sự là *AI trả lời rồi chuyển CS*, thì tuần 01/07 sẽ có 594/610 = **97% ticket AI-first bị chuyển CS**. Đo thực tế con số đó là **8,5%**. Không khớp.

**Kết luận:** trong sheet của bạn, `AI cover` = AI trả lời và **không** chuyển CS; `Chuyển CS` = AI trả lời **rồi mới** chuyển CS. Câu bạn viết nhiều khả năng đang mô tả **cột thứ hai** (`Chuyển CS`), không phải `AI cover`.

Đây chính xác là lý do §1.6 tồn tại: chữ "AI cover" đang mang hai nghĩa trái ngược giữa sheet và spec cũ. Bỏ hẳn chữ đó.

**Tín hiệu xác nhận mạnh nhất:** tỷ lệ reopen khớp trong vòng 1–2 điểm phần trăm trên cả 4 tuần (28,8/27,0 · 16,6/15,3 · 26,6/26,9 · 26,2/26,6). Nghĩa là sau khi bỏ ràng buộc cuối tuần và `turn == 0`, **tập ticket đã đúng**; phần lệch còn lại nằm ở biên tuần, không phải ở logic phân loại.

### 1.6 Bộ nhãn chốt

| Khoá nội bộ | Nhãn UI (chốt) | Định nghĩa (tooltip) |
|---|---|---|
| `ai_end_to_end` | **AI xử lý trọn** | AI trả lời thực chất, không có chuyển CS ở turn sau |
| `ai_then_cs` | **AI trả lời rồi chuyển CS** | AI trả lời thực chất trước, một turn sau đó mới chuyển CS |
| `direct_cs` | **Chuyển CS ngay từ đầu** | Turn đầu là canonical CS transfer |
| `unclassified` | **Chưa phân loại** | Bucket chất lượng dữ liệu, không ép vào 3 nhóm trên |

`AI First` = `ai_end_to_end` + `ai_then_cs`. `Tổng chuyển CS` = `ai_then_cs` + `direct_cs`.
**Không dùng chữ "AI cover" hay "Full AI" ở bất kỳ đâu** — nhãn, export, tooltip, tên biến UI.

### 1.7 Xác nhận "AI phản hồi/ticket TB"

Đo 28 ngày: mean trên **toàn bộ** ticket = 0,97. Mean chỉ trên ticket **AI-first** = 5.834/4.596 = **1,27** — khớp dải 1,27–1,54 trong sheet. → mẫu số là ticket AI-first, không phải toàn bộ ticket.

---

## 2. Quyết định đã chốt

| # | Quyết định | Ghi chú |
|---|---|---|
| D1 | Cohort tuần có **toggle T2–CN / T2–T6**, mặc định **T2–CN** | Server tính sẵn **cả hai** view trong một snapshot; toggle thuần client |
| D2 | Business = **3 chiều chuyển tab**: `Nhóm vấn đề` (mặc định) / `App` / `Nghiệp vụ` | Giá trị gốc Langfuse, không map lại thành 4 nhóm cứng |
| D3 | ">4 turn" đếm theo **số trace trong ticket** | Đo 28 ngày: 137 ticket ≥5 trace ≈ 34/tuần, khớp sheet |
| D4 | UI **Weekly Report first** | Bảng tuần + Copy/CSV là màn hình 1 |
| D5 | Bỏ ràng buộc `turn == 0`; trace-đầu = trace có `(turn, timestamp, id)` nhỏ nhất | Thu hồi 11,3% ticket |
| D6 | Cửa sổ tự co theo dữ liệu có thật | Tuần rỗng hiện "Không có dữ liệu", **không vẽ 0** |
| D7 | Bỏ chữ "AI cover" / "Full AI" khỏi toàn hệ thống | §1.5 — chữ này gây hiểu ngược |

---

## 3. Kiến trúc thay đổi

### 3.1 Đảo chiều nguồn dữ liệu — thay đổi lớn nhất

**Hiện tại:** business + TPE lấy từ observation → `list_observations()` cho từng ticket có transfer (1.241 request tuần tự) → chỉ ticket transfer mới có phân loại.

**Mới:** business + TPE lấy từ `input.other_info.meta` của trace-đầu → **có sẵn trong page trace, 0 request thêm, phủ 100% ticket** kể cả ticket AI xử lý trọn.

Observation chỉ còn dùng cho thứ *không thể lấy từ trace*: `intent`, `skills_used`, `guardrail rule`, `escalation_history_guard` — lấy **bulk theo tên**, không theo trace.

**Hệ quả:** vòng lặp `observation_loader` ở `pipeline.py:331` bị xoá; `analyze_sessions()` không còn nhận `ObservationLoader`.

### 3.2 `langfuse_client.py`

```python
def iter_observations_by_name(
    self, name: str, from_start_time: datetime, to_start_time: datetime
) -> Iterator[dict]
```

- `GET /api/public/observations` với `name`, `fromStartTime`, `toStartTime`, `page`, `limit=100`.
- **`limit` tối đa 100** — đã kiểm chứng, `limit=500` trả `400 too_big`.
- Tái dùng `_parse_page()` và `_request()` sẵn có; retry/backoff giữ nguyên.
- Giữ `list_observations()` cho `inspect-session` của CLI; pipeline không gọi nữa.

### 3.3 `report.py` — enrichment song song + suy giảm mềm

```python
_ENRICHMENT_NAMES = ("route", "execute", "input_guardrail",
                     "skill_guardrail_checked", "escalation_history_guard")
```

- Chạy 5 tên qua `concurrent.futures.ThreadPoolExecutor(max_workers=4)`; mỗi tên phân trang tuần tự.
- **Bỏ `output_guardrail`**: 613 observation, `rule` luôn `output_compliant` — zero thông tin.
- Gộp thành `dict[trace_id, TraceEnrichment]`.
- **Suy giảm mềm bắt buộc:** enrichment lỗi/timeout → vẫn dựng snapshot đầy đủ với `enrichment_status: "partial"`; chiều intent/skill/guardrail hiển thị "Không có dữ liệu". Core metrics + business + TPE **không phụ thuộc** enrichment nên phải sống sót.
- `ReportRun` thêm `enrichment_status`, `observations_fetched`.

Ước tính: 12 tuần ở volume hiện tại ≈ 26k observation/tên → ~260 page/tên; 5 tên qua 4 luồng ≈ 90–120s (hiện ~5 phút).

### 3.4 `cohort.py` — hai định nghĩa tuần + lookback bắt buộc

```python
WeekDefinition = Literal["mon_sun", "mon_fri"]
```

- `cohort_week_for()` giữ nguyên — neo thứ Hai, **giống nhau ở cả hai định nghĩa**. Chỉ khác ở *inclusion*, không khác ở neo tuần → một danh sách ticket, hai mảng weekly.
- `is_week_fully_mature(cohort_week, as_of, week_definition)`: biên hết Chủ nhật (mon_sun) hoặc hết thứ Sáu (mon_fri), cộng 168h.

**Lookback — bug mới phát hiện, phải sửa.** Hiện `query_from_utc = complete_start_local`. Ticket có trace-đầu **trước** mốc đó nhưng còn trace trong cửa sổ sẽ bị lấy nhầm trace-giữa làm trace-đầu → gán sai tuần, sai outcome, sai `ai_first`. Chính lỗi này làm phép đo tuần 01/07 ở §1.5 nhiễu.

Sửa:

```
query_from_utc = complete_start_local - timedelta(days=14)   # LOOKBACK
```

rồi **lọc theo tuần của trace-đầu**, không lọc theo tuần của trace bất kỳ. Ticket có trace-đầu rơi trước `complete_start_local` bị loại khỏi mọi view và **đếm riêng** vào `counts.pre_window_start` (hiển thị ở panel chất lượng dữ liệu, không lẫn vào `left_censored`).

14 ngày chọn theo dữ liệu: session dài nhất quan sát được trải 12 trace; biên an toàn 2 tuần.

### 3.5 `classification.py`

- `classify_session()`: thay `turn0 = next(item for item in ordered if item.turn == 0)` bằng `first = ordered[0]` (`ordered` đã sort `(turn, timestamp, id)`). Ticket không có turn 0 → `data_quality = "no_turn_zero"` — nhãn mới, **vẫn được tính**, không quarantine.
- Bỏ `weekend_start` khỏi đường quarantine; thêm `is_weekend_start: bool` vào `SessionMetrics`.
- Thêm `turn_count = len(ordered)`.
- Thêm `transferred = first_transfer_trace_id is not None`.
- `duplicate_turn` không còn là lỗi chí mạng (turn không còn là khoá tuần tự) — hạ xuống `data_quality = "duplicate_turn"`, giữ ticket, dedupe theo `trace_id`.
- Giữ nguyên `is_substantive_ai_response()` và `is_transfer_response()` — đã kiểm chứng đúng, tỷ lệ reopen khớp sheet trong 1–2pp.

### 3.6 `categories.py` — viết lại classifier

```python
def extract_dimensions(first_trace: TraceRecord, taxonomy: Taxonomy) -> TicketDimensions
```

| Chiều | Nguồn | Xử lý |
|---|---|---|
| `issue_category` | `meta["Thông tin thêm"].category` | nguyên văn; rỗng → `"Không xác định"` |
| `entry_point` | `meta["Thông tin thêm"].sub_source` | nguyên văn |
| `app` | `meta["App"]` | nguyên văn `"241 - Chuyển Tiền ATM"`; tách `app_code` = số đầu để sort |
| `product_code` | `meta["Product Code"]` | nguyên văn; `"N/A"` giữ nguyên `"N/A"` |
| `payment_channel` | `meta["Kênh thanh toán"]` | nguyên văn |
| `tpe_code` | `meta["Mã lỗi TPE"]` | `value.split()[0]` → `"-383"` |
| `tpe_status` | `meta["Mã lỗi TPE"]` | phần còn lại → `"Đang xử lý"` |
| `tpe_step` | `meta["Step result"]` | `parts = value.split("\|")`; step = `parts[2]` nếu `len(parts) >= 3`, ngược lại `parts[0]` |
| `tpe_case` | taxonomy lookup `(tpe_code, tpe_step)` | không có → `None`, **không phải `"unknown"`** |

**Nguyên tắc chống-unknown.** `meta["Mã lỗi TPE"]` tự mang trạng thái tiếng Việt, nên UI luôn hiển thị được `"-217 · Thất bại"` kể cả khi taxonomy chưa có dòng nào cho `-217`. Taxonomy chỉ *thêm* nhãn `case`/`status` chuẩn khi biết, **không** là điều kiện để hiển thị. Chỉ ticket **không có field** mới là `"Không có mã TPE"`.

`classify_guardrail()` giữ logic nhưng đọc từ `TraceEnrichment`, và:
- thêm `off_topic` vào tập rule hợp lệ;
- loại `input_compliant` / `output_compliant` khỏi kết quả (là "không vi phạm", không phải rule).

### 3.7 `config/taxonomy.v2.json`

```jsonc
{
  "version": "v2",
  "transfer": { "semantic_text": "<giữ nguyên v1>" },
  "dimensions": {
    "issue_category": { "meta_path": ["Thông tin thêm", "category"], "fallback": "Không xác định" },
    "app":            { "meta_path": ["App"],             "fallback": "Không xác định" },
    "product_code":   { "meta_path": ["Product Code"],    "fallback": "Không xác định" },
    "entry_point":    { "meta_path": ["Thông tin thêm", "sub_source"], "fallback": "Không xác định" },
    "payment_channel":{ "meta_path": ["Kênh thanh toán"], "fallback": "Không xác định" }
  },
  "tpe": {
    "code_meta_key": "Mã lỗi TPE",
    "step_meta_key": "Step result",
    "step_pipe_index": 2,
    "unmapped_policy": "passthrough",
    "mappings": [ { "code": "-365", "steps": ["-1003", "-1000"], "case": 16, "status": "SYSTEM_ERROR" } ]
  },
  "guardrail": {
    "violation_rules": ["cs_escalation", "empty_message_marker", "max_replies_exceeded",
                        "missing_transaction_id", "prompt_injection_llm", "off_topic"],
    "compliant_rules": ["input_compliant", "output_compliant"]
  },
  "skills": { "prefix_strip": "customer-service/" },
  "intent":  { "min_occurrences": 5, "pattern": "^[a-z0-9_-]{1,64}$", "other_label": "khác" }
}
```

Migration từ v1:
- `step: "-1003 / -1000"` → `steps: ["-1003", "-1000"]`
- `step: "212025/210001/..."` → **liệt kê tường minh, bỏ `"..."`**; tạm `["212025","210001"]`, chờ TPE owner xác nhận
- `step: null` → `steps: []` (khớp mọi step)
- **Không tự bịa** ý nghĩa cho `-217/-380/-993/-268/-369/-1442/-333/-367`. Chúng đi qua `passthrough`, hiển thị `"<code> · <status tiếng Việt từ meta>"`, và xuất hiện trong `unmapped_tpe_codes` để gửi TPE owner.

### 3.8 `models.py`

```python
@dataclass(frozen=True)
class TicketDimensions:
    issue_category: str; app: str; product_code: str
    entry_point: str; payment_channel: str
    tpe_code: str | None; tpe_status: str | None
    tpe_step: str | None; tpe_case: int | None
    skill: str | None; intent: str | None
    guardrail_rule: str | None; escalation_guard_blocked: bool
```

`SessionMetrics` thêm: `is_weekend_start: bool`, `turn_count: int`, `transferred: bool`, `dimensions: TicketDimensions`.

`WeeklySummary` thêm: `week_definition: str`, `has_data: bool`, `reopen_lifetime_numerator: int`, `reopen_lifetime_denominator: int`, `ai_reply_mean_ai_first: float | None`, `gt4_turn_with_cs: int`, `gt4_turn_without_cs: int`, `max_replies_rule_fired: int`.

`TransferCategories` giữ lại như alias tương thích ngược cho `scores.py` (§3.10), **không dùng trong đường dashboard**.

### 3.9 `pipeline.py` — hai view trong một lần chạy

`_summarize_sessions(sessions, window, week_definition)`; `analyze_sessions()` trả `weekly_mon_sun` và `weekly_mon_fri` (view `mon_fri` lọc bỏ `is_weekend_start`).

Invariant kiểm cho **từng view**:
- `total = ai_end_to_end + ai_then_cs + direct_cs + unclassified`
- `ai_first_count = ai_end_to_end + ai_then_cs`
- `transfer_total = ai_then_cs + direct_cs`
- `gt4_turn_with_cs + gt4_turn_without_cs = gt4_turn_total`
- tổng mọi distribution segment = tổng ticket của view đó (bucket `"Không xác định"` bắt buộc tồn tại để đóng tổng)
- `sum(weekly.total_tickets) == len(sessions của view đó)`

**Gate viết lại.** Ngưỡng cũ (`business_unknown > 20%`, `joint_tpe_guardrail_unknown > 50%`) vô nghĩa với mô hình mới. Thay bằng:
- `coverage_issue_category`, `coverage_app`, `coverage_tpe`, `coverage_intent`, `coverage_skill` — tỷ lệ ticket có giá trị, hiển thị nguyên số, **không chặn hiển thị**.
- Chỉ chặn khi `structural_invalid_rate > 5%` (giữ nguyên).
- Panel hiển thị câu người đọc hiểu được: "Coverage TPE 89% — 11% ticket không có mã TPE trong meta", thay badge gate đỏ khó hiểu.

### 3.10 Module hạ nguồn bị vỡ — phần spec cũ bỏ sót

Đổi `SessionMetrics` / `TransferCategories` làm ba module không compile. **Phải xử lý, nếu không P1 dừng ngay:**

| Module | Phụ thuộc | Xử lý |
|---|---|---|
| `scores.py` (404 dòng) | `build_session_scores(metrics, categories, …)` đọc `categories.business/tpe/guardrail_rule` + `gate_status.business_allowed/tpe_allowed/guardrail_allowed` | **Đóng băng.** Ràng buộc dự án là read-only, không ghi score → đường này đã chết trong thực tế. Giữ compile bằng `TransferCategories` alias; thêm docstring `DEPRECATED: read-only deployment does not write scores`. Không mở rộng theo chiều mới |
| `cli.py` (762 dòng) | `dry-run`, `sync`, `inspect-session`, `canary`; `_summary_payload`, `_weekly_rows`, `_investigation_rows`, `_terminal_summary` đọc `AnalysisResult` | `sync`/`canary` ghi score → **giữ nguyên, đánh dấu deprecated**. `dry-run` và `inspect-session` là công cụ debug hữu ích → cập nhật để đọc field mới. `_weekly_rows` phải chọn một view (mặc định `mon_sun`) qua cờ `--week-definition` |
| `artifacts.py` (186 dòng) | ghi JSON artifact, `_assert_safe_keys()` | Cập nhật `_assert_safe_keys()` theo deny-list §7. `artifacts/demo` là demo cũ, **không phải nguồn hiện hành** |
| `dashboard_cache.py` | `ProtectedSnapshotStore` load `runtime/dashboard_snapshot.json` | §4.1 |

Thứ tự an toàn: sửa `models.py` → sửa ngay `scores.py`/`cli.py` cho compile → mới chạy tiếp. Không để `compileall` đỏ qua đêm.

---

## 4. Schema snapshot v3

`_STORAGE_VERSION = 3`.

```jsonc
{
  "generated_at": "...Z",
  "source": { "traces_fetched": 0, "traces_deduplicated": 0, "observations_fetched": 0 },
  "enrichment_status": "complete",
  "data_range": { "first_week_with_data": "2026-06-29", "weeks_without_data": ["2026-05-04"] },
  "views": {
    "mon_sun": { "totals": {}, "outcomes": {}, "ai_first": {}, "reopen": {},
                 "weekly": [], "segments": {}, "rule_gt4": {} },
    "mon_fri": {}
  },
  "coverage": { "issue_category": 0.95, "app": 0.86, "tpe": 0.87, "intent": 0.72, "skill": 0.71 },
  "unmapped_tpe_codes": [ { "code": "-217", "status": "Thất bại", "count": 85 } ],
  "gate_status": {},
  "data_quality": {}
}
```

`views.<v>.segments` = `{ issue_category, app, product_code, skill, intent, tpe, guardrail_rule, entry_point }`; mỗi cái là

```jsonc
{ "<giá trị>": { "total": 0, "ai_first": 0, "transferred": 0, "reopen": 0 } }
```

**Không chỉ count** — có đủ 4 số thì bar list mới hiển thị được *tỷ lệ AI-first theo từng segment*. Đây là thứ PO cần: "nghiệp vụ nào AI làm tệ nhất". Dashboard hiện tại không trả lời được vì chỉ đếm trên nhóm ticket transfer.

### 4.1 Migration snapshot cũ — phải có, nếu không service chết khi khởi động

`runtime/dashboard_snapshot.json` trên đĩa đang là `schema_version: 2`. `DashboardSnapshot.from_storage_dict()` (`dashboard_schema.py:202`) `raise ValueError` khi version lệch.

Yêu cầu: `ProtectedSnapshotStore` bắt `ValueError` khi load, **log rồi bỏ qua file, coi như chưa có snapshot** — service khởi động ở trạng thái `202 / dashboard_not_ready` và tự refresh, thay vì crash. Không viết code convert v2→v3; dữ liệu v2 sai theo §1.4 nên convert là chuyển sai sang schema mới.

Test: đặt file v2 vào runtime dir → `create_app` khởi động được, `/readyz` trả 503 rồi chuyển 200 sau refresh.

### 4.2 Ticket Explorer — mở từ 12 lên 22 trường

```
ticket_id, cohort_week, cohort_status, is_weekend_start, outcome, ai_first,
transferred, reopen_lifetime, reopen_within_7d, ai_reply_count, turn_count,
gt4_turn, issue_category, app, product_code, skill, intent,
tpe_code, tpe_status, guardrail_rule, escalation_guard_blocked, data_quality
```

Filter mới trên `/api/tickets`: `issue_category`, `app`, `product_code`, `skill`, `intent`, `tpe_code`, `gt4_turn`, `transferred`, `is_weekend_start`, `week_definition`.
Nâng `_MAX_QUERY_PAIRS` (`web.py:50`) tương ứng; **giữ nguyên** cơ chế allowlist tên tham số + giới hạn độ dài + chặn tham số lặp ở `web.py:360`. Giá trị filter dạng chuỗi tự do (tên app, intent) phải kiểm theo tập giá trị **có thật trong snapshot**, không theo regex mở.

---

## 5. Đặc tả UI

> Phần này viết lại sau khi đối chiếu tài liệu thiết kế dashboard (Geckoboard, DataCamp, ThoughtSpot, Nielsen Norman Group) và kinh nghiệm thực chiến BI — nguồn ở §11.

### 5.1 Loại dashboard, người đọc, quyết định

Trước khi vẽ bất cứ thứ gì: **dashboard này để ra quyết định gì, ai ra?** Không có ô nào trên trang tồn tại vì "cho đẹp" hoặc "vì có dữ liệu".

Phân loại: **tactical dashboard**, chu kỳ đọc **hằng tuần**, dữ liệu near-live (TTL 5 phút + refresh ~2 phút — **không phải real-time**, phải ghi rõ trên trang).

| Section | Người đọc chính | Quyết định nó phục vụ |
|---|---|---|
| ① KPI tuần | CS lead, PO | Tuần này tốt hơn hay xấu đi? Có cần báo cáo lên không? |
| ② Báo cáo tuần | CS lead | Copy vào báo cáo tuần. Thay thế việc làm tay |
| ③ Xu hướng | PO | AI First đang lên hay đứng? Reopen có xấu đi theo volume không? |
| ④ Segment | PO, dev | **Nghiệp vụ nào AI làm tệ nhất** → ưu tiên cải skill nào tuần tới |
| ⑤ Vì sao chuyển CS | CS lead, dev | Chuyển CS vì lỗi giao dịch (TPE) hay vì bot bí (guardrail)? Hai nguyên nhân này xử lý khác nhau hoàn toàn |
| ⑥ Rule >4 turn | dev | Có user nào đang kẹt vòng lặp với bot không? Rule có chạy đúng không? |
| ⑦ Chất lượng dữ liệu | tất cả | **Có nên tin con số trên trang này không?** |
| ⑧ Explorer | CS agent, dev | Tra một ticket cụ thể; lấy danh sách ticket cần review tay |

Ba nhóm người đọc, ba nhu cầu khác nhau — **không hạ thấp độ sâu để "cho đơn giản"**. Nguyên tắc là *phù hợp với người đọc*, không phải *đơn giản nhất có thể*: CS cần ② và ⑧, PO cần ①③④, dev cần ⑤⑥. Giải quyết bằng thứ tự và khả năng thu gọn, không bằng cắt bớt nội dung.

### 5.2 Ba câu hỏi phải trả lời trong 10 giây

Mở trang, không cần click, không cần cuộn:

1. **Tuần này AI xử lý được bao nhiêu phần ticket, tốt lên hay xấu đi?**
2. **Có gì đang hỏng cần xử lý ngay không?** (user kẹt >4 turn không chuyển CS; reopen tăng vọt)
3. **Số trên trang có đáng tin không?** (điểm chất lượng dữ liệu + thời điểm cập nhật)

Nếu ba câu này không trả lời được trong 10 giây thì bố cục sai — sắp lại, đừng thêm chart.

### 5.3 Nguyên tắc thiết kế

Cấm: gradient tím-xanh, emoji trong metric, card bo góc lớn đổ bóng nhiều lớp, donut chart, nhãn tiếng Anh lẫn tiếng Việt trong cùng một câu.

Dùng:
- Nền `#FFFFFF` / mực `#111418` / viền `#E3E6EA` / nền phụ `#F7F8FA`. Một accent duy nhất `#0068FF`. Trạng thái `#0F9D58` tốt, `#D93025` xấu, `#F29900` cảnh báo. Dark mode qua `prefers-color-scheme`.
- Số dùng `font-variant-numeric: tabular-nums`, canh phải trong bảng.
- Bảng là công dân hạng nhất: viền 1px, header `position: sticky`, zebra rất nhẹ.
- Chart tối giản: line/bar phẳng, không đổ bóng, không animation vào-màn-hình. Animation duy nhất là hover 120ms.
- Mỗi con số có nhãn tiếng Việt đầy đủ + tooltip định nghĩa. Không metric nào để CS phải đoán.
- Trạng thái rỗng viết rõ "Không có dữ liệu trong tuần này" — **không bao giờ vẽ 0**.
- Giữ 100% inline `<style>` / `<script>` để CSP sha256 ở `web.py:197` còn hoạt động. Không asset ngoài, không thư viện chart — vẽ SVG tay như `trendChart` hiện có.

**Nhất quán — thứ phân biệt dashboard chuyên nghiệp với dashboard tự phát:**

- **Một màu = một nghĩa, xuyên suốt toàn trang.** Accent `#0068FF` chỉ dùng cho AI First ở mọi nơi: KPI, đường trend, thanh bar, ô bảng. Đỏ chỉ dùng cho "cần xử lý", không dùng cho "chuyển CS" (chuyển CS không phải lỗi).
- **Tối đa 8 màu phân biệt** trong toàn hệ thống. Vượt quá thì gộp thành "Khác", không thêm màu.
- Khoảng cách chuẩn hoá theo thang 4px: `4 · 8 · 12 · 16 · 24 · 32`. Không có giá trị lẻ.
- Bộ lọc, tab, nút hành động **luôn ở cùng vị trí** ở mọi section. Tab đang chọn có cùng một kiểu highlight ở mọi chỗ.
- Một họ chữ, hai vai trò: chữ thường và số bảng (`tabular-nums`). Không thêm font thứ ba.
- Legend đặt sát chart, không tách xa.
- Tất cả bar list sort **giảm dần theo số lượng**, không sort alphabet.

### 5.4 Luật mã hoá thị giác

Xếp hạng độ chính xác khi mắt người so sánh lượng (NN/g, tiền chú ý — *preattentive*): **độ dài > vị trí 2D > diện tích > góc**.

Suy ra luật cứng cho dự án này:

| Dùng | Không dùng |
|---|---|
| Bar ngang (độ dài) cho mọi so sánh hạng | **Pie / donut** — diện tích, đọc sai |
| Line / scatter (vị trí 2D) cho xu hướng | **Treemap** — diện tích, chỉ hợp khi rảnh rỗi khám phá |
| Bullet bar cho "thực tế vs mục tiêu" | **Gauge / đồng hồ** — góc, tệ nhất, lại tốn diện tích |
| Bảng cho chi tiết vận hành | **3D bất kỳ** — phá hoàn toàn xử lý tiền chú ý |
| Sparkline cho xu hướng nhỏ trong ô | Dual-axis line với hai đơn vị khác nhau |

- **Không bao giờ chỉ dùng màu để mang thông tin.** ~8% nam giới mù màu. Màu luôn đi kèm nhãn chữ, hoặc icon, hoặc vị trí. Đỏ + chữ "cần xử lý", không phải chỉ chấm đỏ.
- Màu + hình dạng kết hợp mạnh hơn từng cái riêng lẻ.
- Bảng xếp hạng luôn **sort giảm dần**, không sort theo alphabet.

**Xung đột đã giải quyết:** thực tiễn BI hay dùng gauge cho điểm chất lượng dữ liệu; NN/g xếp gauge là kém nhất. Chốt: điểm chất lượng dữ liệu dùng **bullet bar ngang + số phần trăm**, không dùng gauge (§5.13).

### 5.5 Bố cục

```
┌─ Thanh trên (dính) ─────────────────────────────────────────────────┐
│ Hiệu quả CS Agent  [T2–CN|T2–T6]  Chất lượng DL 92% ▸  18:27  [↻]  │
│ ① Tuần  ② Báo cáo  ③ Xu hướng  ④ Segment  ⑤ Chuyển CS  ⑥ Rule  ⑧ Ticket │
│ Đang lọc: Tuần 20/07 ✕   Nghiệp vụ: IBFT ✕      [Xoá lọc] [Cách đọc]│
└─────────────────────────────────────────────────────────────────────┘

TIÊU ĐỀ ĐỘNG: "Tuần 20/07–26/07 · cohort T2–CN · 1.722 ticket"
TÓM TẮT BẰNG LỜI: 2–4 câu, xem §5.7

① Tuần này (WTD) vs tuần trước — 4 KPI + delta        ← trạng thái
② BÁO CÁO TUẦN  ← màn hình chính       [Copy] [CSV]   ← trạng thái
③ Xu hướng theo tuần (click cột = lọc toàn trang)      ← so sánh
④ Phân tích theo segment [Nhóm vấn đề|App|Nghiệp vụ|Intent]  ← so sánh
⑤ Vì sao chuyển CS  [Mã TPE | Guardrail/rule | Đã ở CS]      ← chẩn đoán
⑥ Tuân thủ rule >4 turn                                      ← chẩn đoán
⑦ Chất lượng dữ liệu & coverage  (thu gọn, mở từ badge)      ← chi tiết
⑧ Ticket Explorer                                            ← chi tiết
```

Cấu trúc **kim tự tháp ngược**: trạng thái → so sánh → chẩn đoán → chi tiết. Người chỉ cần biết "tuần này ổn không" dừng ở ①②; người điều tra đi tiếp xuống.

Ràng buộc mật độ:
- **①② phải nằm trọn above-the-fold ở 1440×900.** Nếu không đủ chỗ, cắt bớt KPI ở ①, không cắt ②.
- **Tối đa 6 thành phần trực quan mỗi nhóm.** ① đúng 4 KPI; ⑤ đúng 3 panel; ④ một danh sách một lúc (tab), không bày cả bốn.
- Góc **trên-trái** là chỗ mắt rơi vào đầu tiên → đặt KPI quan trọng nhất (AI First) ở đó, không đặt logo hay bộ lọc.
- Khoảng trắng là công cụ phân cấp, không phải chỗ trống cần lấp. Thà để trống còn hơn nhét thêm chart.

### 5.6 Thanh điều hướng & tiện ích

Càng giống một trang web bình thường, người không rành kỹ thuật càng thoải mái. Bốn thứ bắt buộc, luôn ở **cùng một chỗ**, dính khi cuộn:

1. **Nav theo section** — anchor tới ①…⑧, highlight section đang xem. Trang một cột dài nên đây thay cho nút Home/Back.
2. **`[Xoá lọc]`** — reset toàn bộ trạng thái lọc về mặc định. Luôn hiện, kể cả khi chưa lọc (disabled), để người dùng biết nó tồn tại.
3. **`[Cách đọc]`** — mở panel giải thích: định nghĩa 4 outcome (§1.6), cách đọc bảng tuần, tại sao WTD không so sánh được, TPE là gì, guardrail là gì. **Đây là thứ quyết định CS có dùng được dashboard hay không.** Không có nó, mọi câu hỏi đều đổ về bạn.
4. **Badge chất lượng dữ liệu** `Chất lượng DL 92% ▸` — bấm vào nhảy tới ⑦. Xem §5.13.

**Chip lọc đang áp dụng** hiện ngay dưới nav, mỗi chip có `✕`. Không được có trạng thái lọc ẩn — người dùng phải luôn thấy mình đang xem tập con nào.

Bộ lọc toàn cục gom **một chỗ, phía trên nội dung**, không rải rác. Mặc định an toàn: không lọc gì, xem toàn kỳ.

### 5.7 Tiêu đề động + tóm tắt bằng lời

Hai thành phần này mang lại nhiều giá trị nhất cho người không thích đọc chart — tức phần lớn CS.

**Tiêu đề động** ngay dưới thanh trên, đổi theo bộ lọc:

```
Toàn kỳ · cohort T2–CN · 12 tuần · 6.412 ticket
Tuần 20/07–26/07 · cohort T2–CN · 1.722 ticket
Tuần 20/07–26/07 · Nghiệp vụ IBFT · 1.104 ticket
```

**Tóm tắt bằng lời** — 2–4 câu, sinh từ số, **không gọi LLM**, dùng template cố định. Người đọc phải hiểu tình hình mà không cần nhìn chart nào:

```
AI First 79,8% (1.374 ticket), tăng 3,2 điểm so với tuần trước.
Reopen sau AI First 26,2%, gần như đi ngang (−0,4 điểm).
Chuyển CS nhiều nhất do "missing_transaction_id" (622 ticket).
⚠ 11 ticket quá 4 turn nhưng chưa chuyển CS — user có thể đang kẹt.
```

Quy tắc sinh câu:

| Câu | Điều kiện | Template |
|---|---|---|
| 1 | luôn | `AI First {rate}% ({n} ticket), {tăng\|giảm} {delta} điểm so với tuần trước.` — nếu không có tuần trước: `chưa có tuần trước để so sánh.` |
| 2 | luôn | `Reopen sau AI First {rate}%, {tăng\|giảm\|gần như đi ngang} ({delta} điểm).` — `\|delta\| < 1` → "gần như đi ngang" |
| 3 | có ticket chuyển CS | `Chuyển CS nhiều nhất do "{top_reason}" ({n} ticket).` |
| 4 | `gt4_turn_without_cs > 0` | `⚠ {n} ticket quá 4 turn nhưng chưa chuyển CS — user có thể đang kẹt.` — **chữ đỏ** |
| 5 | `enrichment_status == "partial"` | `⚠ Thiếu dữ liệu bổ sung lần đọc này — mục Intent và Nghiệp vụ chưa đầy đủ.` |

Số làm tròn: tỷ lệ 1 chữ số thập phân, delta 1 chữ số thập phân kèm đơn vị "điểm" (điểm phần trăm — **không viết "%"** để tránh nhầm phần trăm tương đối).

Vùng này là `aria-live="polite"` để screen reader đọc khi dữ liệu đổi.

### 5.8 ② Báo cáo tuần — deliverable quan trọng nhất

| Cột | Nguồn |
|---|---|
| Tuần | `01/07 – 05/07` (dải ngày thật, không phải ISO) |
| Tổng ticket | `total_tickets` |
| AI First | `ai_first_count` |
| Tỷ lệ AI First | `ai_first_rate` |
| AI xử lý trọn | `ai_end_to_end_count` |
| AI trả lời rồi chuyển CS | `ai_then_cs_count` |
| Chuyển CS ngay từ đầu | `direct_cs_count` |
| Tổng chuyển CS | `ai_then_cs + direct_cs` |
| Reopen sau AI First | `reopen_lifetime_numerator` |
| Tỷ lệ reopen | `reopen_lifetime_rate` |
| AI phản hồi/ticket TB | `ai_reply_mean_ai_first`, 2 chữ số thập phân |
| >4 turn + CS | `gt4_turn_with_cs` |
| >4 turn không CS | `gt4_turn_without_cs` |
| Chưa phân loại | `unclassified_count` |

- Hàng WTD nền khác + nhãn `WTD — chưa đủ tuần, không so sánh trực tiếp`.
- Tuần không có dữ liệu: một hàng xám "Không có dữ liệu", các ô để trống, **không phải 0**.
- `Tỷ lệ reopen` chỉ hiện khi tuần đã đủ tuổi; chưa đủ thì `—` + tooltip "cần 7 ngày sau tuần cohort".
- **[Copy]** copy TSV vào clipboard (dán thẳng Excel/Sheets). **[CSV]** tải file, **BOM UTF-8** để Excel VN không lỗi font. Cả hai gắn dòng đầu: `# Cohort: T2–CN · Cập nhật 2026-07-29 18:27`.

### 5.9 ③ Xu hướng

Một SVG: cột `Tổng ticket` + đường `Tỷ lệ AI First` (trục phải) + đường `Tỷ lệ reopen`. Hover tooltip đủ số.
**Click một tuần = đặt filter tuần cho toàn bộ ④⑤⑥⑧.** Chip filter hiện đầu trang, có nút xoá.

### 5.10 ④ Phân tích theo segment

Tab `Nhóm vấn đề` (mặc định) / `App` / `Nghiệp vụ` / `Intent`.
Mỗi hàng: `tên segment · thanh ngang · N ticket · % AI First · % chuyển CS`.
Sắp theo N giảm dần, top 12 + gộp `Khác (n mục)` bung được. Click hàng = filter chéo xuống Ticket Explorer.
Tab `Intent` áp bộ lọc riêng tư §7.

### 5.11 ⑤ Vì sao chuyển CS

Ba panel, mẫu số = ticket có chuyển CS:
- **Mã TPE**: `-383 · Đang xử lý · 330`, kèm nhãn `case 2` nếu taxonomy có. Panel phụ "Mã chưa có trong taxonomy" liệt kê code + count.
- **Guardrail / rule**: `missing_transaction_id`, `cs_escalation`, `max_replies_exceeded`, `off_topic`, `empty_message_marker`, `prompt_injection_llm`.
- **Đã ở CS** (`escalation_guard_blocked`): ticket AI im lặng vì đã bàn giao CS — hiện đang lẫn vào "Chưa phân loại".

### 5.12 ⑥ Tuân thủ rule >4 turn

Rule: quá 4 turn phải chuyển CS để user không kẹt với bot.

- Ba số lớn: `Ticket >4 turn`, **`>4 turn nhưng KHÔNG chuyển CS` (cần về 0)**, `Rule max_replies_exceeded đã bắn`.
- Cảnh báo đỏ khi `>4 turn không CS > 0`.
- Link "Xem N ticket" → Explorer với `gt4_turn=true&transferred=false`.
- Ghi rõ dưới panel: `Rule bắn (guardrail) = X` vs `Ticket >4 turn = Y`. **Chênh lệch X↔Y chính là lỗ hổng thực thi rule** — đây là thông tin dev cần nhất trong toàn dashboard.

### 5.13 ⑦ Chất lượng dữ liệu — nói thật về dữ liệu đầu vào

Người ta tin dashboard một cách mù quáng. Nếu dữ liệu đầu vào tệ mà không nói, họ sẽ ra quyết định sai và đó là lỗi của dashboard.

**Điểm chất lượng dữ liệu** — một số duy nhất, luôn hiện ở thanh trên, bấm vào nhảy tới ⑦:

```
dq_score = round(100 * (
    0.40 * structural_valid_rate      +   # 1 − tỷ lệ session bị quarantine
    0.20 * coverage_issue_category    +
    0.20 * coverage_tpe               +
    0.10 * coverage_skill             +
    0.10 * freshness_ok                   # 1 nếu tuổi snapshot ≤ TTL + thời gian refresh, ngược lại 0
))
```

Ngưỡng màu: `≥ 90` xanh · `70–89` vàng · `< 70` đỏ. Hiển thị bằng **bullet bar ngang + số**, không dùng gauge (§5.4).

Panel ⑦ mặc định thu gọn, bên trong nêu **từng luật bị vi phạm, bằng tiếng Việt người thường đọc được** — không phải tên biến:

```
Coverage mã TPE 87%  — 13% ticket không có "Mã lỗi TPE" trong meta
Coverage nhóm vấn đề 95%
Coverage nghiệp vụ 71%  — chỉ ticket có gọi skill mới có giá trị này
Độ tươi: cập nhật 18:27, cách đây 4 phút
8 tuần trong cửa sổ không có dữ liệu (Langfuse chưa có trace trước 29/06/2026)
876 ticket không có mã TPE → mục "Vì sao chuyển CS" chỉ theo dõi coverage, chưa đủ kết luận nguyên nhân
Survey khách hàng: không có trong Langfuse — cần nguồn Freshdesk/CSAT riêng
```

Kèm bảng `unmapped_tpe_codes` (mã TPE chưa có trong taxonomy) — đây là danh sách gửi thẳng cho TPE owner.

**Không được** biến panel này thành badge gate đỏ/xanh khó hiểu như bản cũ. Mỗi dòng phải nói rõ *cái gì thiếu* và *hệ quả là gì*.

### 5.14 ⑧ Ticket Explorer

Giữ regex `[1-9][0-9]{0,19}` và phân trang. Thêm:
- Filter mới (§4.2) dạng chip xoá được.
- Cột mới: `turn_count`, `issue_category`, `app`, `skill`, `tpe_code`, `intent`.
- Chọn cột hiển thị, lưu `localStorage`.
- "Xuất CSV kết quả đang lọc" — client-side từ dữ liệu đã tải, tối đa 1.000 dòng.
- Sort client-side theo cột.

### 5.15 Bốn lớp ngữ cảnh — bắt buộc cho mọi con số

Một con số trần không giúp ai ra quyết định. Mọi KPI và mọi ô bảng phải có đủ:

1. **So sánh** — so với tuần trước, hoặc so với trung bình 4 tuần. Không có mốc so thì không biết 75,6% là tốt hay tệ.
2. **Phạm vi** — đơn vị và khoảng thời gian ghi ngay trong nhãn: `AI First · tuần 20/07–26/07 · cohort T2–CN`.
3. **Độ tươi** — dấu thời gian chính xác, và **dữ liệu cũ phải trông cũ**: quá 15 phút thì badge chuyển vàng kèm chữ "dữ liệu cũ".
4. **Chú thích riêng** — ghi chú nhỏ cho những chỗ dễ hiểu nhầm: `Không tính direct chat`, `WTD chưa đủ tuần`, `Reopen cần 7 ngày sau cohort`.

**Cấu trúc thẻ KPI cố định ở mọi nơi**, không biến thể:

```
Nhãn (đầy đủ tiếng Việt)
GIÁ TRỊ LỚN            ▲ +3,2 điểm
Khoảng thời gian · chú thích nếu có
```

Làm tròn: đếm → số nguyên có phân tách hàng nghìn (`1.374`); tỷ lệ → 1 chữ số thập phân (`79,8%`); trung bình phản hồi → 2 chữ số (`1,27`). **Không bao giờ hiện 3+ chữ số thập phân** — làm số nhỏ trông như biến động lớn.

Ngưỡng cảnh báo hiện trực tiếp trên số, không giấu trong tooltip: `>4 turn không CS` > 0 → đỏ; `dq_score` < 70 → đỏ; reopen tăng > 5 điểm so tuần trước → vàng.

### 5.16 Khả năng tiếp cận

- Tương phản chữ tối thiểu **4.5:1**. Kiểm cả light và dark mode ngay từ đầu, không để cuối.
- Không mang thông tin bằng màu đơn thuần (§5.4).
- Thứ tự `tab` đi đúng thứ tự thị giác; **vòng focus luôn nhìn thấy**, không `outline: none`.
- Mọi bộ lọc, tab, nút Copy/CSV thao tác được bằng bàn phím.
- Bảng dùng markup ngữ nghĩa thật: `<thead>`, `<tbody>`, `<th scope="col">`. Không dùng `<div>` giả bảng — screen reader không đọc được, và CS hay dùng zoom trình duyệt.
- Mỗi chart có **một câu tóm tắt bằng chữ** đặt cạnh (dùng lại cơ chế §5.7) — không ai phải "đọc hình" mới hiểu được.
- Vùng trạng thái và tóm tắt dùng `aria-live="polite"`, không `assertive` — tránh đọc liên tục khi refresh nền.

### 5.17 Responsive

Giữ ràng buộc đã kiểm chứng: không overflow ngang toàn cục ở 390px; bảng cuộn trong `overflow-x: auto` của chính nó; header bảng sticky. ≤768px: ④⑤ xếp dọc, bảng tuần rút còn 6 cột chính + nút "Xem đủ cột".

### 5.18 Hợp đồng DOM

`tests/test_frontend_contract.py` đang assert theo `id`. Đổi UI phải cập nhật test cùng lúc. `id` bắt buộc giữ hoặc khai báo mới trong test:

```
statusChip, liveStatus, updatedAt, refreshButton          // trạng thái
weekDefinitionToggle                                      // MỚI — toggle T2–CN/T2–T6
sectionNav, resetFiltersButton, howToReadButton           // MỚI — §5.6
howToReadPanel                                            // MỚI — nội dung "Cách đọc"
dqBadge, dqScoreValue                                     // MỚI — §5.13, link tới ⑦
dynamicTitle, narrativeSummary                            // MỚI — §5.7, aria-live="polite"
activeFilterChips                                         // MỚI — chip lọc đang áp dụng
kpiGrid                                                   // ①
weeklyRows, weeklyCopyButton, weeklyCsvButton             // ②
trendChart, trendEmpty, trendCaption                      // ③ — caption là câu tóm tắt chart
segmentTabs, segmentList, segmentCaption                  // ④
tpeDistribution, guardrailDistribution, escalationPanel   // ⑤
unmappedTpePanel                                          // ⑤ phụ
ruleGt4Panel, ruleGt4Alert                                // ⑥
coveragePanel, qualityGrid, gateGrid                      // ⑦
ticketFilters, ticketRows, ticketCsvButton                // ⑧
```

Mọi thay đổi `<style>`/`<script>` inline làm CSP sha256 đổi — `_document_security_headers()` (`web.py:197`) tính lại lúc runtime nên **không cần sửa tay**, nhưng test CSP phải chạy lại.

---

## 6. Survey khách hàng — không làm được, và lý do

Đã kiểm: `trace.scores` rỗng trên **toàn bộ 5.062 ticket trace**; project không có score nào. Cột "Survey KH (+/-)" trong sheet đến từ nguồn khác (Freshdesk/CSAT), không phải Langfuse.

**Không đưa cột Survey vào dashboard.** Panel ⑦ ghi một dòng: *"Survey không có trong Langfuse — cần nguồn Freshdesk/CSAT riêng nếu muốn đưa vào."* Đưa cột rỗng vào bảng sẽ làm CS tưởng số 0 là kết quả thật.

---

## 7. Quyền riêng tư

Ràng buộc cũ giữ nguyên (được hiện Ticket ID; cấm User ID, Trans ID, SĐT, tên/email khách, nội dung hội thoại, prompt/response, raw payload, mọi ID nội bộ Langfuse).

**Được phép ra browser** — đã kiểm từng giá trị: `App`, `Product Code`, `Kênh thanh toán`, `Thông tin thêm.category`, `Thông tin thêm.sub_source`, `Mã lỗi TPE`, `Step result` **(chỉ segment mã, bỏ phần mô tả sau dấu `|` cuối)**, `skills_used`, guardrail `rule`, `escalation_guard_blocked`.

**Cấm tuyệt đối, thêm vào deny-list có test** — các key này nằm ngay cạnh trong cùng object `meta` nên rủi ro rò rất cao:

```
UserID · App user · Số điện thoại người dùng · TransID · AppTransId · Mã giao dịch
Zalopay chat keys · System Info · UserAgent · Ghi chú · Ghi chú bên thứ ba
Mô tả · Vấn đề · Thông tin thêm (nguyên object) · title · user_input · comments
Số tài khoản ngân hàng · SĐT đăng ký NH · Thời gian giao dịch · Thời điểm giao dịch
```

**`intent` — rủi ro mới, xử lý riêng.** `route.metadata.intent` do LLM sinh từ nội dung khách nhắn nên về nguyên tắc có thể lọt thông tin khách. Bộ lọc bắt buộc trước khi ghi vào snapshot:

1. khớp `^[a-z0-9_-]{1,64}$` — loại mọi chuỗi có dấu tiếng Việt, khoảng trắng, dãy số dài;
2. xuất hiện **≥ 5 lần** trong toàn snapshot;
3. không qua 1 hoặc 2 → gộp vào `khác`.

Test bắt buộc: duyệt toàn bộ JSON của `/api/dashboard` và `/api/tickets`, assert không chứa chuỗi khớp SĐT VN `(0|84|\+84)[0-9]{8,10}`, UUID, hoặc bất kỳ key nào trong deny-list.

---

## 8. Thứ tự thực hiện

| Giai đoạn | Nội dung | Vì sao trước |
|---|---|---|
| **P0** | `categories.py` đọc meta (App/TPE/category) + parse pipe index 2 + `taxonomy.v2.json` + `off_topic` | Sửa đúng hai lỗi gốc, giá trị cao nhất, không đụng kiến trúc |
| **P1** | Bỏ ràng buộc `turn == 0`; bỏ quarantine cuối tuần; `is_weekend_start`; `turn_count`; **lookback 14 ngày §3.4**; **sửa `scores.py`/`cli.py` cho compile §3.10** | Thu hồi ~35% ticket; lookback quyết định độ chính xác biên tuần |
| **P2** | Hai view tuần + weekly fields mới + gate viết lại + schema v3 + **migration §4.1** | Cho bảng tuần đủ cột |
| **P3** | `iter_observations_by_name` + enrichment song song + suy giảm mềm (intent/skill/guardrail/escalation) | Thêm chiều mới, đồng thời giảm thời gian refresh |
| **P4** | Dựng lại `index.html` theo §5 + cập nhật `test_frontend_contract.py` | Cần schema v3 ổn định trước |
| **P5** | Mở rộng filter `/api/tickets` + Explorer + export | Hoàn thiện |

Sau **mỗi** giai đoạn: `.venv/bin/pytest -q` và `.venv/bin/python -m compileall -q src tests`.

### 8.1 Definition of done từng giai đoạn

| | Xong khi |
|---|---|
| P0 | `coverage_issue_category ≥ 0.90`, `coverage_tpe ≥ 0.85` trên snapshot thật; `unmapped_tpe_codes` không rỗng và có `-217`; không còn giá trị `"other"`/`"unknown"` sinh ra từ keyword matching |
| P1 | `pytest` xanh, `compileall` xanh; `counts.weekend_start_count > 0` và ticket cuối tuần **có mặt** trong `sessions`; `counts.left_censored` giảm mạnh; `counts.pre_window_start` xuất hiện |
| P2 | Cả hai view qua invariant §3.9; service khởi động được với file snapshot v2 cũ trên đĩa |
| P3 | `enrichment_status == "complete"` trên lượt chạy bình thường; chặn observation endpoint → `"partial"` và snapshot vẫn dựng; refresh ≤ 2 phút |
| P4 | 1440px và 390px không overflow ngang; không console error; toggle đổi số đúng; Copy dán Excel đúng cột; **①② nằm trọn above-the-fold ở 1440×900**; tóm tắt bằng lời (§5.7) sinh đúng cho cả 5 template; `[Cách đọc]` và `[Xoá lọc]` hoạt động; tương phản ≥ 4.5:1 ở cả light/dark; đi hết trang bằng bàn phím, focus luôn thấy được |
| P5 | Mọi filter mới trả 422 với giá trị không có trong snapshot; test deny-list §7 xanh |

### 8.2 Chiến lược test không cần API thật

`tests/fixtures/traces.py` đã có sẵn — mở rộng ở đó, **không gọi mạng trong test**:

- Fixture trace phải chứa `input.other_info.meta` với **đúng key tiếng Việt có dấu** (`"Mã lỗi TPE"`, `"Thông tin thêm"`) — lỗi hay gặp là viết không dấu rồi test xanh nhưng prod hỏng.
- Ca biên bắt buộc: ticket không có `turn == 0`; ticket bắt đầu thứ Bảy; ticket có trace-đầu trước `complete_start_local` (kiểm lookback); `Step result` 1 segment và 4 segment; `Mã lỗi TPE` rỗng; intent chỉ xuất hiện 1 lần (phải gộp `khác`); enrichment thiếu hoàn toàn.
- Enrichment inject bằng fake `iter_observations_by_name` trả list cố định — cùng kiểu với `observation_loader` đang dùng trong `test_pipeline.py`.

---

## 9. Kiểm chứng

### 9.1 Đối soát số học — test tự động, cho từng view

```
eligible                = ai_end_to_end + ai_then_cs + direct_cs + unclassified
ai_first_count          = ai_end_to_end + ai_then_cs
transfer_total          = ai_then_cs + direct_cs
gt4_turn_total          = gt4_turn_with_cs + gt4_turn_without_cs
Σ(weekly.total_tickets) = eligible của view đó
Σ(segment[dim].total)   = eligible của view đó      // mọi dim; "Không xác định" đóng tổng
mon_fri.eligible + weekend_start_count = mon_sun.eligible
```

### 9.2 Đối soát nghiệp vụ — baseline đo được

Spec bản trước đặt mục tiêu `AI First ≈ 1.167 / 1.453 / 1.298` (lấy thẳng từ sheet). **Mục tiêu đó sai** — nó giả định dashboard và sheet có cùng biên tuần và cùng tập ticket, chưa được chứng minh. Thay bằng baseline đo thật (§1.5), cohort T2–CN, gồm cuối tuần, không đòi `turn == 0`:

| Tuần | AI First đo được | Sheet | AI xử lý trọn | Sheet | AI rồi chuyển CS | Sheet | Tỷ lệ reopen | Sheet |
|---|---|---|---|---|---|---|---|---|
| 01/07–05/07 | 636 | 610 | 582 | 594 | 54 | 16 | 28,8% | 27,0% |
| 06/07–12/07 | 870 | 1.167 | 822 | 1.129 | 48 | 38 | 16,6% | 15,3% |
| 13/07–19/07 | 1.225 | 1.453 | 1.114 | 1.350 | 111 | 103 | 26,6% | 26,9% |
| 20/07–26/07 | 1.374 | 1.298 | 1.220 | 1.189 | 154 | 109 | 26,2% | 26,6% |

Đọc bảng này:

- **Tỷ lệ reopen khớp trong 1–2 điểm phần trăm trên cả bốn tuần** → tập ticket và logic reopen đã đúng. Đây là kiểm chứng mạnh nhất hiện có.
- **AI First còn lệch, và lệch hai chiều** (20/07 đo *cao hơn* sheet). Không phải undercount hệ thống → không sửa được bằng cách nới thêm phạm vi.
- Baseline này đo với fetch bắt đầu 2026-06-29, **chưa có lookback §3.4**, nên tuần 01/07 nhiễu biên. Sau khi P1 thêm lookback, số sẽ đổi — **đo lại rồi mới so**.

**Quy trình đối soát bắt buộc sau P1** (không phải cổng số cứng):

1. Chạy lại bảng trên với lookback bật.
2. Nếu lệch AI First ≤ 10% mỗi tuần → chấp nhận, ghi chênh lệch vào panel ⑦.
3. Nếu > 10% ở tuần nào → **ngồi với người giữ sheet**, lấy 20 Ticket ID chỉ có ở một bên, tra `inspect-session`, xác định nguyên nhân. Nghi vấn ưu tiên: sheet dùng ngày tạo ticket Freshdesk chứ không phải thời điểm trace đầu; sheet gồm cả `source == "chat"`; sheet chốt số giữa tuần.
4. Không phát hành cho CS trước khi bước 3 xong. Một dashboard lệch 20% mà không giải thích được sẽ mất niềm tin vĩnh viễn.

### 9.3 Coverage kỳ vọng sau P0

| Chiều | Hiện tại | Kỳ vọng |
|---|---|---|
| Business không phải "Khác" | 54% | ≥ 95% (`issue_category`) |
| TPE có giá trị | 29,4% | ≥ 87% |
| Guardrail rule | 98% | ≥ 98% (thêm `off_topic`) |

### 9.4 Riêng tư, UI, hiệu năng

- **Riêng tư:** chạy test deny-list §7 trên snapshot thật; duyệt toàn bộ trang Ticket Explorer; grep response tìm SĐT/UUID/ID nội bộ.
- **UI:** Chrome 1440px và 390px — không overflow ngang toàn cục, bảng cuộn trong khung, không console error, toggle T2–CN/T2–T6 đổi số đúng, click cột chart lọc toàn trang, Copy dán Excel đúng cột.
- **Hiệu năng:** đo wall-clock một lượt refresh đầy đủ, kỳ vọng ≤ 2 phút (hiện ~5 phút). Test suy giảm mềm: chặn observation endpoint, xác nhận snapshot vẫn dựng với `enrichment_status: "partial"`.

---

## 10. Việc ngoài phạm vi code

1. **Rotate `LANGFUSE_SECRET_KEY`** — Basic Auth từng xuất hiện trong process arguments. Cập nhật `.env`, giữ mode 0600.
2. Gửi TPE owner danh sách `unmapped_tpe_codes` (`-217`, `-380`, `-993`, `-268`, `-369`, `-1442`, `-333`, `-367`) + xác nhận đủ mã cho `"212025/210001/..."`.
3. Chốt bộ nhãn §1.6 với CS trước khi phát hành. Chữ "AI cover" đang mang hai nghĩa trái ngược — không chốt thì mọi cuộc họp sẽ tranh cãi.
4. Đối soát §9.2 bước 3 với người giữ sheet.
5. Dashboard đang chạy ở `127.0.0.1:8765` là **code cũ, số sai**. Không gửi link cho CS trước khi xong P1.
6. Docker chưa build/chạy được trên máy local (không có Docker runtime) — **không tuyên bố container đã kiểm chứng**.
7. Sau khi có bản P4, **ngồi cạnh 2 CS agent thật, giao một việc cụ thể** ("tìm ticket tuần trước quá 4 turn mà chưa chuyển CS"), bấm giờ. Không hỏi "trông có đẹp không" — đo thời gian tới quyết định. Việc nào chặn thì sửa trước, phần thẩm mỹ tính sau.

---

## 11. Tham khảo

Nguyên tắc ở §5 lấy từ:

- [Geckoboard — Dashboard design best practices](https://www.geckoboard.com/resources/dashboard-design/) — góc trên-trái, phân cấp bằng kích thước, tỷ lệ data-ink, tránh pie/area, loại metric không hành động được, bối cảnh so sánh và ngưỡng cảnh báo.
- [DataCamp — Dashboard design tutorial](https://www.datacamp.com/tutorial/dashboard-design-tutorial) — quy trình 6 bước, quy tắc 10 giây, kim tự tháp ngược, cấu trúc thẻ KPI cố định, bốn lớp ngữ cảnh, giới hạn bảng màu, khả năng tiếp cận.
- [ThoughtSpot — Dashboard design examples & best practices](https://www.thoughtspot.com/data-trends/dashboard-design-examples-best-practices) — quy tắc tối đa 6 thành phần mỗi nhóm, 5–7 KPI chính, above-the-fold, mỗi tab trả lời một câu hỏi nghiệp vụ.
- [Nielsen Norman Group — Dashboards: making charts and graphs easier to understand](https://www.nngroup.com/articles/dashboards-preattentive/) — xếp hạng tiền chú ý (độ dài > vị trí 2D > diện tích > góc), loại bỏ pie/treemap/gauge/3D, không dùng màu đơn thuần.
- Kinh nghiệm thực chiến BI (sản xuất, y tế, cải tiến dịch vụ) — bắt đầu từ *quyết định* chứ không từ dữ liệu (§5.1); điều hướng giống website cho người không rành kỹ thuật (§5.6); tiêu đề động và tóm tắt bằng lời (§5.7); **nói thật về chất lượng dữ liệu đầu vào** (§5.13); "phù hợp với người đọc" thay vì "đơn giản nhất có thể" (§5.1).
