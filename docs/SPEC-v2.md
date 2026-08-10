# Spec v2 — Langfuse Weekly CS Dashboard

> Trạng thái: **đã implement đến storage/browser schema v15**. Người viết spec: Claude. Người implement: GPT 5.6 sol.
> Baseline measurement của spec: 2026-07-29, dữ liệu thật từ `https://langfuse.zalopay.vn`, API read-only.
> Contract P0 active là Langfuse-only theo `docs/superpowers/specs/2026-07-31-langfuse-only-p0-data-integrity-design.md`; contract này thắng mọi mô tả P0 Freshdesk/applicability cũ (§3.9, §9.4).
> Contract Transstatus/Step result được sửa ngày 2026-07-31 sau khi đối chiếu observation nguồn; phần này thắng mọi mô tả legacy về pipe/taxonomy.
> Tài liệu này **thay thế** mọi mô tả metric trong `README.md` khi có mâu thuẫn.

---

## 0. Context

Baseline trước khi viết spec đúng về kỹ thuật (323 test pass, không rò PII)
nhưng **sai về sản phẩm**:

- Phân loại business đọc sai key metadata, còn chẩn đoán TPE từng bị trộn giữa
  metadata Freshdesk, taxonomy nội bộ và output thật của tool.
- Phạm vi ticket hẹp hơn thực tế ~35% → số không khớp báo cáo tay CS đang dùng.
- Nhiều trường giá trị cao có sẵn trong Langfuse nhưng chưa dùng (intent,
  skills, guardrail rule, escalation guard và Step result thật từ tool).

CS/PO không thể tin một dashboard cho ra con số khác sheet của chính họ. Spec này sửa gốc: đổi nguồn dữ liệu, mở phạm vi ticket, thêm chiều phân tích, dựng lại UI theo hướng "Weekly Report first".

---

## 1. Bằng chứng đã đo

Mọi số dưới đây đo trực tiếp trên API, không suy luận.

### 1.1 Nguồn dữ liệu thật của trace

`GET /api/public/traces?fields=core,io` là nguồn trace duy nhất và trả
`input.other_info.meta` — object phẳng khoảng 30 key do hệ thống upstream ghi
vào Langfuse:

```
input.other_info.meta = {
  "App": "241 - Chuyển Tiền ATM",
  "Product Code": "TF007 - IBFT money transfer trong Zalopay App",
  "Mã lỗi TPE": "-383 Đang xử lý",
  "Step result": "<legacy pipe string>",  // KHÔNG dùng làm Step result
  "Kênh thanh toán": "38 - TK Zalo Pay",
  "Bank Code": "ZPMB - MBBank",
  "KYC level": "3", "Hạng thành viên": "Thành viên",
  "Platform": "ZPA", "OS": "IOS",
  "Nguồn submit ticket": "Chatbot",
  "Thông tin thêm": { "category": "Thanh toán-IBFT", "sub_source": "tranxdetail" },
  ...  // + field PII: UserID, App user, TransID, Số điện thoại người dùng
}
```

`meta["Step result"]` là chuỗi metadata legacy có thể chứa mô tả. Dashboard
không được tách bất kỳ segment nào từ chuỗi này, không được serialize nó và
không được dùng nó làm Step result.

P0 và các metric lõi Langfuse chỉ đọc dữ liệu đã có trên root trace/observation
Langfuse. Không API ticket khác, local overlay, demo data, fixture hay giá trị
nhập tay nào được tham gia các metric đó hoặc quyết định pass/fail. Ngoại lệ
hẹp cho CSAT Freshdesk và outcome-reconciliation nằm ở §6.1; các số đó luôn là
lane riêng có nhãn nguồn và không sửa metric Langfuse. Link sang hệ thống ticket
vẫn chỉ là operator navigation sau click, không tự phát sinh server-side read.

### 1.2 Hai lỗi nguồn dữ liệu — contract đã sửa

| | Baseline trước sửa | Vấn đề đo được |
|---|---|---|
| **Business** | `categories.py:165` `classify_business()` match keyword trên `other_info.title` + whitelist meta key `["category","type","usecase","domain",…]` | Whitelist **không khớp key nào có thật**. Meta dùng `App`, `Product Code`, `Thông tin thêm.category`. Duy nhất `type` khớp nhưng giá trị là `public`/`private`. → fallback `other` = 572/1243 |
| **TPE** | Có lúc lấy `meta["Mã lỗi TPE"]`, tách `meta["Step result"]` rồi map qua taxonomy | Metadata Freshdesk và output tool là hai contract khác nhau. Coi segment thứ ba là Step result, đặt `Case`, hoặc gán canonical status là diễn giải không được nguồn xác nhận |

**Nguồn TPE duy nhất được chấp nhận cho dashboard:** observation có tên chính
xác `tool:get_transaction_processing_engine_data`. Chỉ đọc hai field cùng một
`output.result`: `transstatus` và `stepresult`. Giữ token nguồn, không map qua
taxonomy và không gán ý nghĩa. Grain của phân phối là cặp
`(transstatus, step_result)`.

Live observation đã xác nhận các cặp ví dụ như `(-365, -1013)`,
`(-365, -1006)` và `(-365, -1024)`. Những ví dụ này chỉ chứng minh hình dạng
contract; spec không diễn giải ý nghĩa của mã.

[V1 + Adapter — Error Codes](https://confluence.zalopay.vn/x/EJCfBw) và
[Bank — Response code](https://confluence.zalopay.vn/x/0jCPAw) là tài liệu
tham chiếu theo domain cho owner. Chúng không xác nhận rằng segment trong
metadata legacy là `output.result.stepresult`, nên dashboard không tự join hoặc
suy diễn từ hai trang này.

### 1.3 Các nguồn dữ liệu enrichment giá trị cao

`GET /api/public/observations?name=<name>&fromStartTime=…` — bulk theo tên, có `traceId`, không cần gọi từng trace:

| Observation | Field | Đo 3 ngày |
|---|---|---|
| `route` (GENERATION) | `metadata.intent` | ~100 intent: `interbank-fund-transfer_recovery` 234, `_dispute` 44, `_issue` 43, `refund_request` 22, `complaint_about_processing_time` 20, `transaction_reversal_fraud` 15… |
| `execute` (SPAN) | `metadata.skills_used` | `customer-service/interbank-fund-transfer` 645, `/topup` 132, `/withdraw` 108 — skill đã dùng |
| `input_guardrail`, `skill_guardrail_checked`, `output_guardrail` | `output.rule`, trạng thái blocked/passed, stage và skill an toàn | Các rule nguồn gồm `missing_transaction_id`, `cs_escalation`, `empty_message_marker`, `max_replies_exceeded`, `prompt_injection_llm`, `off_topic` và các alias live đã allowlist |
| `escalation_history_guard` | `output.blocked` | true 114/878 = 13% — ticket đã ở CS nên AI im lặng |
| `tool:get_transaction_processing_engine_data` | `output.result.transstatus`, `output.result.stepresult` | Cặp mã nguồn cho chẩn đoán TPE; thiếu `stepresult` được đo riêng, không suy ra từ metadata |

Các alias live như `empty_input`, `off_topic_llm`, `prompt_injection`,
`system_prompt_leak` và `tone_check_error` phải được allowlist rõ ràng. Dashboard
giữ nguyên `rule` nguồn cho Dev, còn wording dành cho CS/PO được map bằng code
deterministic; giá trị ngoài allowlist fail-closed về lý do chưa xác định.

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
| `direct_cs` | **Chuyển CS ngay từ đầu** | Turn đầu có phản hồi chuyển CS khớp một template đã được duyệt |
| `unclassified` | **Chưa phân loại** | Bucket chất lượng dữ liệu, không ép vào 3 nhóm trên |

`AI First` = `ai_end_to_end` + `ai_then_cs`. `Tổng chuyển CS` = `ai_then_cs` + `direct_cs`.
**Không dùng chữ "AI cover" hay "Full AI" ở bất kỳ đâu** — nhãn, export, tooltip, tên biến UI.

### 1.7 Xác nhận "AI phản hồi/ticket TB"

Đo 28 ngày: mean trên **toàn bộ** ticket = 0,97. Mean chỉ trên ticket **AI-first** = 5.834/4.596 = **1,27** — khớp dải 1,27–1,54 trong sheet. → mẫu số là ticket AI-first, không phải toàn bộ ticket.

---

## 2. Quyết định đã chốt

| # | Quyết định | Ghi chú |
|---|---|---|
| D1 | Cohort tuần có **toggle T2–T6 / T2–CN**, mặc định **T2–T6** | Server tính sẵn **cả hai** view trong một snapshot; toggle thuần client |
| D2 | Segment = **5 chiều chuyển tab**: `Category` (mặc định) / `App` / `Product Code` / `Skill` / `Intent` | Giá trị gốc Langfuse, không map lại thành nhóm cứng |
| D3 | ">3 lượt xử lý" đếm theo **số trace trong ticket** | Ticket có ít nhất 4 trace thuộc nhóm này |
| D4 | UI **Weekly Report first** | Bảng tuần + Copy/CSV là màn hình 1 |
| D5 | Bỏ ràng buộc `turn == 0`; trace-đầu = trace có `(turn, timestamp, id)` nhỏ nhất | Thu hồi 11,3% ticket |
| D6 | Cửa sổ tự co theo dữ liệu có thật | Tuần rỗng hiện "Không có dữ liệu", **không vẽ 0** |
| D7 | Bỏ chữ "AI cover" / "Full AI" khỏi toàn hệ thống | §1.5 — chữ này gây hiểu ngược |

---

## 3. Kiến trúc thay đổi

### 3.1 Tách đúng nguồn dữ liệu theo chiều

**Category, App, Product Code, entry point và payment channel** lấy từ
`input.other_info.meta` của trace-đầu. Các chiều này có sẵn trong page trace,
không cần observation riêng.

**Transstatus và Step result** chỉ lấy từ observation
`tool:get_transaction_processing_engine_data`: lần lượt
`output.result.transstatus` và `output.result.stepresult`. Hai field phải được
đọc từ cùng một result và giữ thành một cặp; không bổ sung từ
`meta["Mã lỗi TPE"]` hoặc `meta["Step result"]`.

Các enrichment còn lại (`intent`, `skills_used`, guardrail rule và
`escalation_history_guard`) cũng lấy bulk theo tên, không gọi tuần tự theo từng
ticket.

**Hệ quả:** vòng lặp `observation_loader` theo từng session ở
`pipeline.py:331` bị xoá; `analyze_sessions()` nhận enrichment đã được gom theo
trace/session.

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

### 3.3 `enrichment.py` — enrichment song song + suy giảm mềm

```python
ENRICHMENT_NAMES = ("route", "execute", "input_guardrail",
                    "skill_guardrail_checked", "output_guardrail",
                    "escalation_history_guard",
                    "tool:get_transaction_processing_engine_data")
```

- Chạy 7 tên qua `concurrent.futures.ThreadPoolExecutor(max_workers=4)`; mỗi tên phân trang tuần tự.
- `output_guardrail` là lane bắt buộc từ v14 vì có thể chứa
  `cs_escalation` bị chặn. Không được dùng baseline cũ chỉ quan sát
  `output_compliant` để loại lane này.
- Gộp thành `dict[trace_id, TraceEnrichment]`.
- **Suy giảm mềm bắt buộc:** enrichment lỗi/timeout → vẫn dựng snapshot với
  `enrichment_status: "partial"`; Intent, Skill, Guardrail và Step result có
  thể chưa đầy đủ. Core outcome, Category, App và Product Code vẫn phải sống
  sót.
- `ReportRun` thêm `enrichment_status`, `observations_fetched`.

Wall-clock của refresh phải được đo lại với đủ 7 observation lane; không dùng
ước tính 5 lane cũ làm bằng chứng phát hành.

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

- `classify_session()`: sắp xếp trace theo `(turn, timestamp, id)` rồi quét toàn bộ chuỗi để tìm trace có thể phân loại đầu tiên. Output guardrail/system-only, rỗng hoặc kỹ thuật không phải outcome; một phản hồi AI thực chất hoặc phản hồi chuyển CS khớp chính xác một template đã duyệt ở trace sau vẫn được dùng. Chỉ khi hết chuỗi không có trace nào như vậy mới là `unclassified`. Ticket không có turn 0 → `data_quality = "no_turn_zero"` — nhãn mới, **vẫn được tính**, không quarantine.
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
| `tpe_signals` | `apply_trace_enrichment()` từ `tool:get_transaction_processing_engine_data` | tuple bất biến các cặp `(transstatus, step_result)` đã validate; `step_result` có thể `None`; `extract_dimensions()` khởi tạo rỗng |

**Contract Step result.**

- Chỉ nhận scalar integer hoặc numeric string ASCII khớp `^-?\d{1,6}$`; `bool`,
  chuỗi pipe, mô tả, unicode lookalike hoặc token quá dài bị loại.
- `transstatus` không hợp lệ → bỏ observation. `transstatus` hợp lệ nhưng
  `stepresult` thiếu/không hợp lệ → giữ `(transstatus, None)`.
- Nhiều observation có thể tạo nhiều cặp cho cùng ticket; dedupe đúng cặp,
  không làm mất cặp khác.
- Không đọc `meta["Step result"]`, không map `Case`, không gán canonical status
  và không suy luận ý nghĩa.
- UI dùng literal `Không có Step result` khi phần tử thứ hai là `None`.

`classify_guardrail()` giữ logic nhưng đọc từ `TraceEnrichment`, và:
- thêm `off_topic` vào tập rule hợp lệ;
- loại `input_compliant` / `output_compliant` khỏi kết quả (là "không vi phạm", không phải rule).

### 3.7 `config/taxonomy.v2.json`

```jsonc
{
  "version": "v2",
  "transfer": { "semantic_texts": ["<template đã duyệt>", "<biến thể đã duyệt>"] },
  "dimensions": {
    "issue_category": { "meta_path": ["Thông tin thêm", "category"], "fallback": "Không xác định" },
    "app":            { "meta_path": ["App"],             "fallback": "Không xác định" },
    "product_code":   { "meta_path": ["Product Code"],    "fallback": "Không xác định" },
    "entry_point":    { "meta_path": ["Thông tin thêm", "sub_source"], "fallback": "Không xác định" },
    "payment_channel":{ "meta_path": ["Kênh thanh toán"], "fallback": "Không xác định" }
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

Mapping TPE còn tồn tại trong taxonomy cũ chỉ là dữ liệu legacy cho luồng
forensic/rollback. Dashboard production candidate không đọc mapping đó và
không dùng danh sách “unmapped” làm cảnh báo.

### 3.8 `models.py`

```python
@dataclass(frozen=True)
class TicketDimensions:
    issue_category: str; app: str; product_code: str
    entry_point: str; payment_channel: str
    # Langfuse-trace metadata retained only for aggregate P0 verification:
    tpe_code: str | None; tpe_status_raw: str | None
    tpe_status_canonical: str | None; tpe_step: str | None
    tpe_case: int | None
    # The only TPE source allowed into dashboard projection:
    tpe_signals: tuple[tuple[str, str | None], ...]
    skill: str | None; intent: str | None
    guardrail_rule: str | None; escalation_guard_blocked: bool
```

Các field `tpe_code/tpe_status_*/tpe_step/tpe_case` nếu còn trong model chỉ được
đọc từ canonical first normalized Langfuse trace để tạo aggregate P0
privacy-safe. Chúng không được bổ sung từ local overlay và không được dùng để
dựng `transfer_reasons`, dashboard `coverage.tpe`, Ticket Explorer hoặc copy
user-facing. Từ projection v5 trở đi (hiện tại v9), chỉ `tpe_signals` có
authority.

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
- `transfer_reasons.step_result_missing.denominator = transfer_total`
- `transfer_reasons.step_result_missing.count` bằng tổng count của các tuần và
  không vượt mẫu số
- tổng mọi distribution segment = tổng ticket của view đó (bucket `"Không xác định"` bắt buộc tồn tại để đóng tổng)
- `sum(weekly.total_tickets) == len(sessions của view đó)`

**Gate viết lại.** Ngưỡng cũ (`business_unknown > 20%`, `joint_tpe_guardrail_unknown > 50%`) vô nghĩa với mô hình mới. Thay bằng:
- `coverage_issue_category`, `coverage_app`, `coverage_intent`,
  `coverage_skill` — tỷ lệ ticket có giá trị. `coverage_tpe` chỉ đo ticket có
  Transstatus hợp lệ từ observation nguồn; không bổ sung từ metadata. Tất cả
  hiển thị nguyên số và **không chặn hiển thị**.
- Chỉ chặn khi `structural_invalid_rate > 5%` (giữ nguyên).
- Panel hiển thị câu người đọc hiểu được:
  `"Coverage Transstatus {x}% — {y}% ticket không có observation TPE nguồn"`,
  kèm coverage Step result trên ticket chuyển CS, thay badge gate đỏ khó hiểu.

**P0 Langfuse-only verifier — release data gate.**

Mẫu số P0 là mọi raw root session có `input.source == "ticket"`; chỉ
`input.source == "chat"` bị loại. Valid session đếm một lần, keyed session lỗi
và ticket unit không có key vẫn nằm trong mẫu số. Không source segment, entry
point, category hoặc điều kiện field-present nào được thu hẹp mẫu số.

Verifier chỉ dùng canonical first normalized Langfuse trace và phát các giá trị
authority:

```text
coverage_issue_category =
  issue_category_present_count / ticket_count
coverage_tpe =
  tpe_present_count / ticket_count
p0_issue_category_pass =
  ticket_count > 0 and coverage_issue_category >= 0.90
p0_tpe_pass =
  ticket_count > 0 and coverage_tpe >= 0.85
p0_pass =
  p0_issue_category_pass and p0_tpe_pass
```

Không đọc local overlay hoặc API ticket khác. Missing giữ nguyên missing và
population rỗng fail closed. Snapshot `coverage.tpe` vẫn là coverage
Transstatus observation-source ở trên, tách biệt với `coverage_tpe` của gate
P0 metadata.

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

## 4. Schema snapshot v15

`_STORAGE_VERSION = 15`. Contract chẩn đoán TPE nguồn được đưa vào từ v5:
loại các field suy diễn `code/status/step/case/mapped` khỏi
`transfer_reasons.tpe` và thay bằng cặp nguồn `transstatus/step_result`. v6
thêm `same_period`; v7 tách `Nhiều skill` khỏi `Chưa ghi nhận`; v8 thêm CSAT
Freshdesk nullable theo từng view; v9 thêm comment survey đã redact; v10 thêm
thời điểm phản hồi `comments[].responded_at` để lọc/sắp xếp đúng. v11 thay
projection CSAT bằng grain ticket, thêm breakdown outcome/Skill/Category,
`feedback_entries` và `TicketRow.csat_satisfaction`. v12 thêm
`outcome_reconciliation` metadata-only theo từng view. Mẫu số đối chiếu chỉ gồm
ticket `AI xử lý trọn` có Ticket ID Freshdesk hợp lệ mà job có thể fetch; tổng
outcome Langfuse không bị thay đổi. v13 thêm `TicketRow.opened_at`, lấy đúng
`SessionMetrics.turn0_timestamp` và serialize canonical UTC ISO để Ticket
Explorer hiển thị ngày giờ Việt Nam và sort toàn cục. v14 thêm partition
`transfer_reasons.triggers`: đúng một lý do cho mỗi ticket đã chuyển CS, được
neo vào `SessionMetrics.first_transfer_trace_id`; ID trace chỉ dùng trong bộ
nhớ và không được serialize. Mọi lần đổi shape phải bump version cùng batch và
cập nhật exact-key Python/Zod. v15 đưa enum `transfer_reason` đã qua cùng
boundary validation vào TicketRow; ticket đã chuyển CS luôn có một reason
(fallback `unknown`), ticket chưa chuyển luôn là `null`. Rule/source/stage/skill
vẫn chỉ tồn tại ở bảng tổng hợp.

Các số dưới đây chỉ minh hoạ shape, không phải snapshot đo được:

```jsonc
{
  "schema_version": 15,
  "generated_at": "...Z",
  "source": { "traces_fetched": 0, "traces_deduplicated": 0, "observations_fetched": 0 },
  "enrichment_status": "complete",
  "data_range": { "first_week_with_data": "2026-06-29", "weeks_without_data": ["2026-05-04"] },
  "views": {
    "mon_sun": { "totals": {}, "outcomes": {}, "ai_first": {}, "reopen": {},
                 "weekly": [], "segments": {}, "by_week": {},
                 "same_period": null, "csat": null,
                 "outcome_reconciliation": null, "rule_gt4": {} },
    "mon_fri": {}
  },
  "coverage": { "issue_category": 0.95, "app": 0.86, "tpe": 0.62, "intent": 0.72, "skill": 0.71 },
  "unmapped_tpe_codes": [],
  "gate_status": {},
  "data_quality": {}
}
```

`views.<v>.same_period` là `null` hoặc chứa `cutoff_date`,
`cutoff_weekday`, `current`, `baseline` và `by_week`. Cutoff là ngày
Asia/Ho_Chi_Minh đã hoàn tất gần nhất; mọi tuần trong `by_week`, kể cả tuần
đang chạy, đều cắt ở cùng thứ. Mỗi key trong `same_period.by_week` phải tồn tại
trong `views.<v>.by_week`. Block là `null` khi chưa có ngày nào hoàn tất trong
tuần, tuần của view đã hoàn tất, hoặc có ít hơn hai tuần baseline không rỗng.

`unmapped_tpe_codes` chỉ còn là compatibility field rỗng trong một release,
không thuộc frontend contract và không được render. Nó sẽ bị xoá cùng
compatibility hook sau cửa sổ rollback.

`views.<v>.segments` = `{ issue_category, app, product_code, skill, intent, tpe, guardrail_rule, entry_point }`; mỗi cái là

```jsonc
{ "<giá trị>": { "total": 0, "ai_first": 0, "transferred": 0, "reopen": 0 } }
```

**Không chỉ count** — có đủ 4 số thì bar list mới hiển thị được *tỷ lệ
AI-first theo từng segment*. Đây là thứ PO cần: "Product Code hoặc Category nào
AI làm tệ nhất". Dashboard hiện tại không trả lời được nếu chỉ đếm trên nhóm
ticket transfer.

`views.<v>.transfer_reasons` và từng tuần dùng cùng contract:

```jsonc
{
  "observed_transfer_denominator": 320,
  "step_result_missing": { "count": 74, "denominator": 320 },
  "tpe": [
    { "transstatus": "-365", "step_result": "-1013", "count": 42 },
    { "transstatus": "-365", "step_result": null, "count": 11 }
  ],
  "triggers": [
    {
      "reason": "skill_suggested_transfer",
      "rule": "cs_escalation",
      "source": "skill_guardrail_checked",
      "stage": "output",
      "skill": "interbank-fund-transfer",
      "count": 31
    },
    {
      "reason": "ai_response_requires_transfer",
      "rule": "cs_escalation",
      "source": "output_guardrail",
      "stage": null,
      "skill": null,
      "count": 12
    },
    {
      "reason": "unknown",
      "rule": null,
      "source": null,
      "stage": null,
      "skill": null,
      "count": 4
    }
  ],
  "guardrail": [],
  "escalation_guard_blocked": { "count": 18, "denominator": 320 }
}
```

- Grain duy nhất của `tpe` là `(transstatus, step_result)`.
- `step_result_missing.count` là số ticket chuyển CS không có Step result hợp
  lệ trong bất kỳ TPE signal nguồn nào; `denominator` phải bằng
  `observed_transfer_denominator`.
- `Ticket` đếm ticket duy nhất theo từng cặp; observation lặp lại cùng cặp trong
  một ticket chỉ tính một lần. `Tỷ trọng` bằng `Ticket` chia
  `observed_transfer_denominator`.
- Các tín hiệu diagnostic có thể overlap; tổng count của các row TPE không
  buộc bằng mẫu số ticket chuyển CS và tổng tỷ trọng có thể vượt 100%.
- Không có `status`, `case`, `mapped`, mô tả hoặc field suy diễn nào trong row.
- `triggers` là partition độc quyền: tổng `count` bắt buộc bằng
  `observed_transfer_denominator`. Mỗi ticket chỉ đọc blocked event trên đúng
  trace `first_transfer_trace_id`; event ở trace trước/sau không được thay thế.
- Grain của trigger là `(reason, rule, source, stage, skill)`. Hai đường
  `cs_escalation` từ `skill_guardrail_checked · stage=output` và
  `output_guardrail` phải là hai row khác nhau.
- Không tìm được blocked event hợp lệ trên trace chuyển CS đầu tiên thì dùng
  row `unknown`, với toàn bộ `rule/source/stage/skill = null`. Không suy lý do
  từ TPE, tên observation, trace khác hoặc nội dung hội thoại.

### 4.1 Migration snapshot cũ — phải có, nếu không service chết khi khởi động

`DashboardSnapshot.from_storage_dict()` raise `ValueError` khi version lệch.
`ProtectedSnapshotStore` phải bắt lỗi, log không chứa payload rồi bỏ qua file,
coi như chưa có snapshot. Service khởi động ở trạng thái
`202 / dashboard_not_ready` và tự refresh, thay vì crash.

Không convert snapshot cũ sang v15. Riêng v4 có shape TPE mang ý nghĩa sai nên
phải bị bỏ qua và đọc lại nguồn, không “nâng version” trên dữ liệu cũ. Mọi
version trước v15 đều cold refresh. Test bắt buộc: đặt file version cũ vào
runtime dir → `create_app` khởi động được, `/readyz` trả 503 rồi chuyển 200 sau
refresh v15.

### 4.2 Ticket Explorer — projection 25 trường

```
ticket_id, opened_at, cohort_week, cohort_status, is_weekend_start, outcome, ai_first,
transferred, reopen_lifetime, reopen_within_7d, ai_reply_count, turn_count,
gt4_turn, issue_category, app, product_code, skill, intent,
tpe_code, tpe_status, guardrail_rule, transfer_reason, escalation_guard_blocked,
csat_satisfaction, data_quality
```

`opened_at` là thời điểm mở ticket theo turn đầu tiên trong Langfuse. Browser
hiển thị cả ngày và giờ theo Asia/Ho_Chi_Minh; CSV dùng cùng cách viết. Cột được
sort bằng backend trên toàn bộ tập kết quả trước khi phân trang. Không thêm
filter ngày giờ riêng: filter tuần đã là control thời gian chính và tránh hai
control chồng nghĩa.

Hai tên `tpe_code`/`tpe_status` được giữ đúng một release để không phá
visibility key và client cũ:

- `tpe_code` chỉ mang một `transstatus` khi ticket có đúng một giá trị
  Transstatus duy nhất trong `tpe_signals` nguồn.
- Thiếu hoặc có nhiều Transstatus khác nhau → `tpe_code = null`; không chọn một
  giá trị đại diện.
- `tpe_status` luôn `null`; frontend không hiển thị hay diễn giải status.
- Nhãn user-facing của `tpe_code` là `Transstatus`. Không có URL hay metadata
  legacy nào được thêm vào TicketRow.

Filter mới trên `/api/tickets`: `issue_category`, `app`, `product_code`,
`skill`, `intent`, `tpe_code`, `gt4_turn`, `transferred`,
`is_weekend_start`, `week_definition`.

Sort toàn cục trên `/api/tickets`: `sort_by` chỉ nhận đúng 25 field TicketRow ở
trên; `sort_direction` chỉ nhận `asc|desc`, không được đứng một mình và mặc định
`asc` khi bỏ trống. Backend lọc trước, sort toàn bộ tập khớp rồi mới phân trang.
Giá trị `null` luôn nằm cuối ở cả hai chiều; giá trị bằng nhau tie-break bằng
Ticket ID dạng số tăng dần. Query sort sai phải trả 422 đã sanitize, không echo
giá trị đầu vào.

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
| ④ Segment | PO, dev | **Product Code hoặc Category nào AI làm tệ nhất** → ưu tiên cải skill nào tuần tới |
| ⑤ Chẩn đoán chuyển CS | CS lead, dev | Transstatus/Step result nào xuất hiện, và hệ thống ghi nhận lý do nào trên đúng trace chuyển CS đầu tiên? |
| ⑥ Ticket có hơn 3 lượt xử lý | CS lead, dev | Có ticket nào có hơn 3 trace/lượt xử lý nhưng vẫn chưa chuyển CS để mở danh sách kiểm tra? |
| ⑦ Chất lượng dữ liệu | tất cả | **Có nên tin con số trên trang này không?** |
| ⑧ Explorer | CS agent, dev | Tra một ticket cụ thể; lấy danh sách ticket cần review tay |

Ba nhóm người đọc, ba nhu cầu khác nhau — **không hạ thấp độ sâu để "cho đơn giản"**. Nguyên tắc là *phù hợp với người đọc*, không phải *đơn giản nhất có thể*: CS cần ② và ⑧, PO cần ①③④, dev cần ⑤⑥. Giải quyết bằng thứ tự và khả năng thu gọn, không bằng cắt bớt nội dung.

### 5.2 Ba câu hỏi phải trả lời trong 10 giây

Mở trang, không cần click, không cần cuộn:

1. **Tuần này AI xử lý được bao nhiêu phần ticket, tốt lên hay xấu đi?**
2. **Có gì đang hỏng cần xử lý ngay không?** (user kẹt >3 lượt xử lý không chuyển CS; reopen tăng vọt)
3. **Số trên trang có đáng tin không?** (điểm chất lượng dữ liệu + thời điểm cập nhật)

Nếu ba câu này không trả lời được trong 10 giây thì bố cục sai — sắp lại, đừng thêm chart.

### 5.3 Nguyên tắc thiết kế

Cấm: gradient tím-xanh, emoji trong metric, card bo góc lớn đổ bóng nhiều lớp, donut chart, nhãn tiếng Anh lẫn tiếng Việt trong cùng một câu.

Dùng:
- Nền `#FFFFFF` / mực `#111418` / viền `#E3E6EA` / nền phụ `#F7F8FA`. Một accent duy nhất `#0068FF`. Trạng thái `#0F9D58` tốt, `#D93025` xấu, `#F29900` cảnh báo.
- Theme mặc định theo `prefers-color-scheme` ở lần truy cập đầu hoặc khi không
  có preference hợp lệ. App shell phải có nút nhìn thấy được, hiển thị trạng
  thái `Sáng` / `Tối` và cho phép override ngay; lựa chọn chỉ được lưu literal
  `light|dark` vào key không nhạy cảm `weekly-cs-theme-v1`. Giá trị thiếu, hỏng
  hoặc ngoài allowlist phải fallback an toàn về system preference.
- Logo và Z graphic phải đổi cùng resolved theme, chỉ dùng đúng cặp asset chính
  thức đã bundle same-origin: full-colour/light Z cho light, white/dark Z cho
  dark. Không thêm inline boot script/style, external request, `unsafe-inline`
  hoặc bất kỳ nới lỏng CSP nào để triển khai theme.
- Số dùng `font-variant-numeric: tabular-nums`, canh phải trong bảng.
- Bảng là công dân hạng nhất: viền 1px, header `position: sticky`, zebra rất nhẹ.
- Chart tối giản: line/bar phẳng, không đổ bóng, không animation vào-màn-hình. Animation duy nhất là hover 120ms.
- Mỗi con số có nhãn tiếng Việt đầy đủ + tooltip định nghĩa. Không metric nào để CS phải đoán.
- Trạng thái rỗng viết rõ "Không có dữ liệu trong tuần này" — **không bao giờ vẽ 0**.
- Bản dashboard phát hành là packaged SPA với bundle CSS/JavaScript đã hash,
  thay thế trang delivery inline cũ. Giữ CSP nghiêm: không inline code,
  không asset ngoài. Chart library là lựa chọn implementation thay thế được;
  semantic SVG, keyboard/cross-filter, khoảng dữ liệu thiếu, CSP và bundle
  budget mới là contract.

**Nhất quán — thứ phân biệt dashboard chuyên nghiệp với dashboard tự phát:**

- **Một màu = một nghĩa, xuyên suốt toàn trang.** Accent `#0068FF` chỉ dùng cho AI First ở mọi nơi: KPI, đường trend, thanh bar, ô bảng. Đỏ chỉ dùng cho "cần xử lý", không dùng cho "chuyển CS" (chuyển CS không phải lỗi).
- **Tối đa 8 màu phân biệt** trong toàn hệ thống. Vượt quá thì gộp thành "Khác", không thêm màu.
- Khoảng cách chuẩn hoá theo thang 4px: `4 · 8 · 12 · 16 · 24 · 32`. Không có giá trị lẻ.
- Bộ lọc, tab, nút hành động **luôn ở cùng vị trí** ở mọi section. Tab đang chọn có cùng một kiểu highlight ở mọi chỗ.
- Một họ chữ, hai vai trò: chữ thường và số bảng (`tabular-nums`). Không thêm font thứ ba.
- Legend đặt sát chart, không tách xa.
- Tất cả bar list mặc định sort **giảm dần theo số lượng**. Với semantic table,
  người đọc có thể đổi cột và chiều sort từ header; biểu đồ không đổi thứ tự
  ngoài contract riêng của nó.

**Nguồn brand asset — contract bổ sung của production frontend.**

`../docs/zalopay-guideline` là upstream canonical duy nhất cho logo, Z graphic,
app icon và Aeonik Pro; không lấy từ Downloads hoặc nguồn mạng. Project giữ
bản curated dùng để build dưới
`assets/brand/{logos,graphics,icons,fonts/source,fonts/web}` và manifest
`assets/brand-provenance.json`. Logo, app icon, hai Z graphic và ba OTF source
phải đối chiếu byte-for-byte với nguồn canonical; ba WOFF2
Regular/Medium/Bold là derivative sinh xác định từ OTF và phải qua kiểm tra
provenance trước release. Project không copy `.ai`/PDF, và browser bundle không
chứa OTF source. Đường dẫn canonical không phải runtime dependency: production
build chỉ đọc bản đã kiểm chứng trong project.

Icon Langfuse là third-party integration asset, không phải Zalopay brand asset
và không được ghi vào brand manifest. Nó nằm tại
`assets/icons/langfuse-icon.svg`; `assets/third-party-provenance.json` pin URL
brand asset chính thức và hash exact-copy. SVG phải được bundle same-origin,
không tải từ Langfuse khi mở trang. CI checkout độc lập chỉ được tuyên bố kiểm
hai manifest, inventory, hash đã pin và browser budget; chỉ lượt audit có
sibling canonical mới được tuyên bố đã đối chiếu trực tiếp nguồn guideline
Zalopay.

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
- Bảng xếp hạng mặc định **sort giảm dần** để ưu tiên vấn đề có volume lớn;
  header của semantic table vẫn cho phép người đọc sort lại khi chẩn đoán.

**Xung đột đã giải quyết:** thực tiễn BI hay dùng gauge cho điểm chất lượng dữ liệu; NN/g xếp gauge là kém nhất. Chốt: điểm chất lượng dữ liệu dùng **bullet bar ngang + số phần trăm**, không dùng gauge (§5.13).

### 5.5 Bố cục

```
┌─ Thanh trên (dính) ─────────────────────────────────────────────────┐
│ Hiệu quả CS Agent  [T2–T6|T2–CN]  Chất lượng DL 92% ▸  18:27  [↻]  │
│ ① Tuần  ② Báo cáo  ③ Xu hướng  ④ Segment  ⑤ Chuyển CS  ⑥ Rule  ⑧ Ticket │
│ Đang lọc: Tuần 20/07 ✕   Product Code: IBFT ✕   [Xoá lọc] [Cách đọc]│
└─────────────────────────────────────────────────────────────────────┘

TIÊU ĐỀ ĐỘNG: "Tuần 20/07–24/07 · cohort T2–T6 · 1.722 ticket"
TÓM TẮT BẰNG LỜI: 2–4 câu, xem §5.7

① Tuần này (WTD) — 4 KPI; so cùng số ngày đã hoàn tất khi đủ baseline ← trạng thái
② BÁO CÁO TUẦN  ← màn hình chính       [Copy] [CSV]   ← trạng thái
③ Xu hướng [Cùng kỳ đến Tn | Tuần đủ] (click tuần = lọc) ← so sánh
④ Phân tích theo segment [Category|App|Product Code|Skill|Intent]  ← so sánh
⑤ Chẩn đoán chuyển CS [Transstatus + Step result | Lý do chuyển CS] ← chẩn đoán
⑥ Ticket quá 3 lượt [Tổng | Đã chuyển CS | Chưa chuyển CS]   ← chẩn đoán
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

Càng giống một trang web bình thường, người không rành kỹ thuật càng thoải mái. Năm thứ bắt buộc, luôn ở **cùng một chỗ**, dính khi cuộn:

1. **Nav theo section** — anchor tới ①…⑧, highlight section đang xem. Trang một cột dài nên đây thay cho nút Home/Back.
2. **`[Xoá lọc]`** — reset toàn bộ trạng thái lọc về mặc định. Luôn hiện, kể cả khi chưa lọc (disabled), để người dùng biết nó tồn tại.
3. **`[Cách đọc]`** — mở panel giải thích: định nghĩa 4 outcome (§1.6), cách đọc
   bảng tuần, cách WTD so cùng số ngày đã hoàn tất và vì sao có lúc không đủ
   baseline để so, TPE là gì, guardrail là gì. **Đây là thứ quyết định CS có
   dùng được dashboard hay không.** Không có nó, mọi câu hỏi đều đổ về bạn.
4. **Badge chất lượng dữ liệu** `Chất lượng DL 92% ▸` — bấm vào nhảy tới ⑦. Xem §5.13.
5. **Theme `[Sáng]` / `[Tối]`** — nút luôn nhìn thấy trong app shell, cho biết
   mode hiện tại và mode sẽ chuyển tới trong accessible name. Nút thao tác được
   bằng bàn phím, có focus ring và target tối thiểu 44×44px trên mobile. Lần đầu
   theo system; lựa chọn explicit được khôi phục sau reload.

Copy WTD trong panel là:
`Với WTD, phần tóm tắt và biểu đồ chỉ so các tuần tới cùng ngày đã hoàn tất khi đủ baseline; bảng tuần vẫn giữ số thực của tuần.`

**Chip lọc đang áp dụng** hiện ngay dưới nav, mỗi chip có `✕`. Không được có trạng thái lọc ẩn — người dùng phải luôn thấy mình đang xem tập con nào.

Bộ lọc toàn cục gom **một chỗ, phía trên nội dung**, không rải rác. Mặc định an toàn: không lọc gì, xem toàn kỳ.

### 5.7 Tiêu đề động + tóm tắt bằng lời

Hai thành phần này mang lại nhiều giá trị nhất cho người không thích đọc chart — tức phần lớn CS.

**Tiêu đề động** ngay dưới thanh trên, đổi theo bộ lọc:

```
Toàn kỳ · cohort T2–T6 · 12 tuần · 6.412 ticket
Tuần 20/07–24/07 · cohort T2–T6 · 1.722 ticket
Tuần 20/07–26/07 · Product Code IBFT · 1.104 ticket
```

**Tóm tắt bằng lời** — 2–4 câu, sinh từ số, **không gọi LLM**, dùng template cố định. Người đọc phải hiểu tình hình mà không cần nhìn chart nào:

```
AI First 79,8% (1.374 ticket), tăng 3,2 điểm so với tuần trước.
Reopen sau AI First 26,2%, gần như đi ngang (−0,4 điểm).
Tín hiệu chuyển CS nổi bật: Thiếu mã giao dịch (622 ticket).
11 ticket có hơn 3 lượt xử lý mà chưa chuyển CS — khách nhiều khả năng đang mắc kẹt.
```

Quy tắc sinh câu:

| Câu | Điều kiện | Template |
|---|---|---|
| 1 | tuần hoàn tất | `AI First {rate}% ({n} ticket), {tăng\|giảm} {delta} điểm so với tuần trước.` — nếu không có tuần trước: `chưa có tuần trước để so sánh.` |
| 1 | WTD + `same_period` | `AI First {rate}% ({n} ticket). Tính tới {thứ}, cùng kỳ {weeks_used} tuần trước trung bình {baseline}% — tuần này đang {nhỉnh hơn\|thấp hơn} {delta} điểm.` |
| 1 | WTD không có `same_period` | `AI First {rate}% ({n} ticket).` |
| 2 | tuần hoàn tất | `Reopen sau AI First {rate}%, {tăng\|giảm\|gần như đi ngang} ({delta} điểm).` — `\|delta\| < 0,5` → "gần như đi ngang" |
| 2 | WTD + `same_period` | `Reopen sau AI First {rate}%, cùng kỳ {weeks_used} tuần trước {baseline}%.` |
| 2 | WTD không có `same_period` | `Reopen sau AI First {rate}%.` |
| 3 | có ticket chuyển CS | `Tín hiệu chuyển CS nổi bật: {signal} ({n} ticket).` |
| 4 | `gt4_turn_without_cs > 0` | `{n} ticket có hơn 3 lượt xử lý mà chưa chuyển CS — khách nhiều khả năng đang mắc kẹt.` — **chữ đỏ** |
| 5 | `enrichment_status == "partial"` | `Lần đọc này chưa lấy đủ dữ liệu phụ, nên Intent, Skill, Guardrail và Step result còn thiếu.` |

Số làm tròn: tỷ lệ 1 chữ số thập phân, delta 1 chữ số thập phân kèm đơn vị "điểm" (điểm phần trăm — **không viết "%"** để tránh nhầm phần trăm tương đối).

Vùng này là `aria-live="polite"` để screen reader đọc khi dữ liệu đổi.

Thanh việc cần chú ý chỉ giữ ba cảnh báo có hành động tiếp theo:

- `{n} ticket có hơn 3 lượt xử lý mà chưa chuyển CS` → mở Ticket Explorer với
  bộ lọc `>3 lượt xử lý`.
- `{rate} bản ghi lỗi cấu trúc, vượt ngưỡng 5%` → kiểm tra pipeline.
- `Lần đọc này chưa lấy đủ dữ liệu phụ` → chờ lần làm mới kế tiếp.

Độ phủ Skill nằm cạnh bảng Skill. Số thiếu Step result nằm cạnh chẩn đoán
chuyển CS; hai cảnh báo này không lặp lại trên thanh đầu trang.

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
| >3 lượt xử lý + CS | `gt4_turn_with_cs` |
| >3 lượt xử lý không CS | `gt4_turn_without_cs` |
| Chưa phân loại | `unclassified_count` |

- Hàng WTD nền khác + nhãn `WTD — chưa đủ tuần, không so sánh trực tiếp`.
- Tuần không có dữ liệu: một hàng xám "Không có dữ liệu", các ô để trống, **không phải 0**.
- `Tỷ lệ reopen` chỉ hiện khi tuần đã đủ tuổi; chưa đủ thì `—` + tooltip "cần 7 ngày sau tuần cohort".
- Bảng mặc định sắp tuần mới nhất trước và cho phép sort view theo từng header
  bằng raw value. `aria-sort` và chỉ báo `↑/↓` phải luôn phản ánh chiều hiện
  hành; giá trị thiếu luôn nằm cuối ở cả hai chiều.
- Hai export luôn giữ thứ tự tuần mới nhất trước và đúng 14 cột, không phụ thuộc
  sort tạm thời trên màn hình. Đây là thứ tự hand-off có quản trị.
- **[Chép TSV]** đưa một bảng TSV sạch vào clipboard để dán thẳng
  Excel/Sheets: dòng 1 là đúng 14 header, các dòng sau luôn đủ 14 cell, không
  chèn metadata preamble.
- **[CSV]** tải file có **BOM UTF-8** để Excel VN không lỗi font. Record đầu là
  metadata cố định đủ 14 field: `# Cohort`, giá trị cohort, `Cập nhật`,
  timestamp và 10 field rỗng; record thứ hai là 14 header, sau đó mới tới dữ
  liệu.

### 5.9 ③ Xu hướng

Hai panel SVG thẳng hàng dùng chung trục tuần: panel trên có cột
`Tổng ticket` và `Ticket AI First`; panel dưới có đường `Tỷ lệ AI First` và
`Tỷ lệ reopen`. Không dùng dual-axis.

Khi view đang chọn có `same_period`, hiện một control hai trạng thái
`[Cùng kỳ đến Tn | Tuần đủ]` phía trên cả hai panel, mặc định `Tuần đủ`.
Chọn cùng kỳ phải đổi cả hai panel từ cùng một `same_period.by_week`, gồm cả
tuần đang chạy; caption ghi đúng thứ cutoff, ví dụ
`Mọi tuần đều cắt tới thứ Tư để so cùng kỳ.` Đổi cohort luôn reset về
`Tuần đủ`; `same_period = null` thì không render control.

**Click một tuần = đặt filter tuần cho toàn bộ ④⑤⑥⑧.** Chip filter hiện đầu
trang, có nút xoá. Bảng 14 cột ở §5.8 không đổi theo control chart.

### 5.10 ④ So sánh theo thuộc tính ticket

Tab `Category` (mặc định) / `App` / `Product Code` / `Skill` / `Intent`.
Mỗi hàng: `tên segment · thanh ngang · N ticket · % AI First · % chuyển CS`.
Sắp theo N giảm dần, top 12 + gộp `Khác (n mục)` bung được. Click hàng = filter chéo xuống Ticket Explorer.
Tab `Intent` áp bộ lọc riêng tư §7.

Không lặp lại tuần đang xem ngay dưới title khi title/scope của trang đã nói
đúng tuần đó. Mọi row có `Ticket = 0` bị ẩn ở presentation; backend vẫn giữ
bucket bắt buộc để validation không bị yếu đi.

### 5.11 ⑤ Chẩn đoán chuyển CS

Hai panel, mẫu số = ticket có chuyển CS:
- **Transstatus và Step result**: semantic table có đúng bốn cột
  `Transstatus | Step result | Ticket | Tỷ trọng`. Mỗi row là một cặp nguồn
  `(transstatus, step_result)` từ cùng observation. Hiển thị token nguyên gốc;
  `step_result = null` dùng literal `Không có Step result`.
- **Lý do chuyển CS**: partition độc quyền từ blocked event trên đúng trace
  chuyển CS đầu tiên. Bảng có đúng sáu cột
  `Lý do chuyển CS | Giá trị nguồn | Nguồn phát hiện | Skill | Ticket | Tỷ lệ`.
  Wording dành cho CS/PO đứng trước; `rule`, observation source và stage nguyên
  gốc đứng sau cho Dev đối chiếu. Tổng Ticket của bảng bắt buộc bằng mẫu số.
  `Skill đề xuất chuyển CS` (`cs_escalation`,
  `skill_guardrail_checked · stage=output`) và
  `Phản hồi AI được nhận diện là cần chuyển CS` (`cs_escalation`,
  `output_guardrail`) là hai đường riêng, không được gộp.
- Ticket không có blocked event hợp lệ trên trace chuyển CS đầu tiên hiển thị
  `Chưa xác định được từ trace`; các cột nguồn là `—`. UI không nhận trace ID.

Không hiển thị `Case`, canonical status, mô tả, mapped/unmapped hoặc taxonomy.
Ngay dưới bảng, hiển thị coverage đo được theo template:
`{thiếu}/{mẫu số} ticket chuyển CS ({tỷ lệ}) không có Step result. {hệ quả}`.
Hệ quả là `Phần lớn ca chuyển CS hiện chưa truy được tới bước lỗi cụ thể.` chỉ
khi tỷ lệ thiếu lớn hơn 50%; các scope thấp hơn dùng
`Các ca này hiện chưa truy được tới bước lỗi cụ thể.`
Nếu mẫu số bằng 0, nói rõ không có ticket chuyển CS thay vì hiện tỷ lệ 0%.

Các row TPE vẫn có thể overlap và chỉ là tín hiệu quan sát. Không dùng TPE để
suy hoặc ghi đè lý do. Bảng `Lý do chuyển CS` là partition riêng; không render panel
`escalation_guard_blocked`: PO đã đọc ngược nghĩa metric này và nó không tạo
được hành động riêng; field chỉ còn ở projection cho compatibility/điều tra.

### 5.12 ⑥ Ticket có hơn 3 lượt xử lý

Hiển thị bảng ba dòng theo đúng scope tuần/toàn kỳ đang chọn:

- `Tổng` = `gt4_turn_with_cs + gt4_turn_without_cs`.
- `Đã chuyển CS` = `gt4_turn_with_cs`.
- `Chưa chuyển CS` = `gt4_turn_without_cs`.
- Khi dòng chưa chuyển lớn hơn 0, `Xem N ticket chưa chuyển CS` mở Explorer
  với `gt4_turn=true&transferred=false` và giữ filter tuần hiện hành.

Không hiển thị `max_replies_rule_fired`, “rule đã bắn”, “khoảng trống rule” hay
“guard chặn”. Đây là telemetry dành cho điều tra backend, không phải một metric
CS/PO có thể đọc đúng hoặc hành động độc lập.

### 5.13 ⑦ Chất lượng dữ liệu — nói thật về dữ liệu đầu vào

Không hiển thị điểm tổng hợp hoặc badge “Skill: thiếu … ticket” ở header. Điểm
trộn nhiều đại lượng không giải thích được và top-level coverage không cùng
scope với tuần đang xem.

Panel mặc định thu gọn và chỉ nêu dữ kiện đọc được:

- thời điểm snapshot Langfuse và tuổi dữ liệu;
- chiều dữ liệu có độ phủ thấp nhất, dưới dạng `{x}% ticket có dữ liệu
  {dimension} để phân nhóm`;
- phần còn thiếu không lọc được theo dimension đó, kèm câu phân biệt rõ đây là
  độ đầy đủ instrumentation chứ không phải tỷ lệ ticket không được xử lý;
- mẫu số ghi thẳng là toàn bộ ticket T2–CN trong toàn kỳ, không giả vờ cùng
  scope với tuần/cohort đang xem.

Không có score, gauge, meter, bảng mã taxonomy hay cảnh báo kỹ thuật. Coverage
Step result thuộc ngay panel TPE vì nó dùng mẫu số ticket chuyển CS riêng.

### 5.14 ⑧ Ticket Explorer

Giữ regex `[1-9][0-9]{0,19}` và phân trang. Thêm:
- Filter mới (§4.2) dạng chip xoá được.
- Cột mới: `opened_at`, `csat_satisfaction`, `turn_count`, `issue_category`,
  `app`, `skill`, `tpe_code`, `intent`;
  `tpe_code` hiển thị bằng nhãn `Transstatus` theo compatibility contract §4.2,
  còn `tpe_status` không được render.
- `opened_at` hiển thị ngày giờ Việt Nam và sort toàn cục được; filter tuần là
  control thời gian duy nhất.
- Cột `Ticket` là row header và định danh điều tra bắt buộc, luôn hiển thị và
  luôn có trong CSV. Các cột còn lại được chọn hiển thị và lưu `localStorage`.
- Ticket ID hợp lệ là link Freshdesk
  `https://vngzalopay.freshdesk.com/a/tickets/{ticketId}`. Cùng ô có một link
  icon Langfuse chính thức tới trang Tracing đã lọc `Session ID = Ticket ID`
  theo URL đã duyệt ở §7. Icon là trang trí (`alt=""`); accessible name của
  link phải nói rõ destination, Ticket ID và việc mở tab mới. Cả hai mở tab
  mới với `rel="noopener noreferrer"`; ID sai regex giữ nguyên text, không tạo
  link.
- "Xuất CSV kết quả đang lọc" — client-side ghép các page API theo đúng filter
  và global sort hiện hành, lấy tối đa 1.000 dòng đầu tiên của toàn tập đã sort;
  không lấy 1.000 dòng mặc định rồi mới sort cục bộ.
- CSV chỉ xuất dữ liệu cột, gồm Ticket ID thô; không xuất URL hay nhãn điều
  hướng/icon Freshdesk hoặc Langfuse.
- Click header đổi `sort_by`/`sort_direction`, reset về page 1 và refetch; sort
  áp dụng cho toàn bộ kết quả trước pagination, không chỉ page đang thấy.

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

Ngưỡng cảnh báo hiện trực tiếp trên số, không giấu trong tooltip: `>3 lượt xử lý không CS` > 0 → đỏ; `dq_score` < 70 → đỏ; reopen tăng > 5 điểm so tuần trước → vàng.

### 5.16 Khả năng tiếp cận

- Tương phản chữ tối thiểu **4.5:1**. Kiểm cả light và dark mode ngay từ đầu, không để cuối.
- Không mang thông tin bằng màu đơn thuần (§5.4).
- Thứ tự `tab` đi đúng thứ tự thị giác; **vòng focus luôn nhìn thấy**, không `outline: none`.
- Mọi bộ lọc, tab, nút Copy/CSV thao tác được bằng bàn phím.
- Skip link `Tới nội dung chính` luôn focus vào landmark
  `main#dashboardMain`, kể cả trạng thái loading. Khi scroll tới đích, main
  phải nằm dưới app shell sticky; contract này phải được kiểm ở viewport nhỏ
  nhất `320×568`, không chỉ desktop.
- Bảng dùng markup ngữ nghĩa thật: `<thead>`, `<tbody>`, `<th scope="col">`. Không dùng `<div>` giả bảng — screen reader không đọc được, và CS hay dùng zoom trình duyệt.
- Mỗi chart có **một câu tóm tắt bằng chữ** đặt cạnh (dùng lại cơ chế §5.7) — không ai phải "đọc hình" mới hiểu được.
- Vùng trạng thái và tóm tắt dùng `aria-live="polite"`, không `assertive` — tránh đọc liên tục khi refresh nền.

### 5.17 Responsive

Giữ ràng buộc đã kiểm chứng: không overflow ngang toàn cục ở 390px; bảng cuộn trong `overflow-x: auto` của chính nó; header bảng sticky. ≤768px: ④⑤ xếp dọc, bảng tuần rút còn 6 cột chính + nút "Xem đủ cột".

### 5.18 Hợp đồng DOM

`tests/test_frontend_contract.py` đang assert theo `id`. Đổi UI phải cập nhật test cùng lúc. `id` bắt buộc giữ hoặc khai báo mới trong test:

```
statusChip, liveStatus, updatedAt, refreshButton          // trạng thái
weekDefinitionToggle                                      // MỚI — toggle T2–T6/T2–CN
sectionNav, resetFiltersButton, howToReadButton           // MỚI — §5.6
howToReadPanel                                            // MỚI — nội dung "Cách đọc"
dqBadge, dqScoreValue                                     // MỚI — §5.13, link tới ⑦
dynamicTitle, narrativeSummary                            // MỚI — §5.7, aria-live="polite"
activeFilterChips                                         // MỚI — chip lọc đang áp dụng
kpiGrid                                                   // ①
weeklyRows, weeklyCopyButton, weeklyCsvButton             // ②
trendChart, trendEmpty, trendCaption                      // ③ — caption là câu tóm tắt chart
segmentTabs, segmentList, segmentCaption                  // ④
tpeDistribution, guardrailDistribution                     // ⑤; id compatibility, UI là “Lý do chuyển CS”
stepResultCoverage                                        // ⑤ coverage đo được
ruleGt4Panel, ruleGt4Alert                                // ⑥
coveragePanel, qualityGrid, gateGrid                      // ⑦
ticketFilters, ticketRows, ticketCsvButton                // ⑧
```

Mọi thay đổi frontend phải được build lại thành packaged SPA có asset hash; test
CSP và delivery SPA phải chạy lại. Trang inline cũ chỉ là chế độ `legacy` trong
cửa sổ rollback, không phải delivery contract của bản phát hành.
Các tính năng v11–v14 như CSAT, thời gian mở ticket, sort toàn cục và lý do
chuyển CS chỉ được
cam kết trên SPA; legacy có thể thiếu các trường này và không phải release
candidate.

---

## 6. Survey khách hàng — không làm được, và lý do

Đã kiểm: `trace.scores` rỗng trên **toàn bộ 5.062 ticket trace**; project không có score nào. Cột "Survey KH (+/-)" trong sheet đến từ nguồn khác (Freshdesk/CSAT), không phải Langfuse.

**Không đưa cột Survey vào dashboard.** Panel ⑦ ghi một dòng: *"Survey không có trong Langfuse — cần nguồn Freshdesk/CSAT riêng nếu muốn đưa vào."* Đưa cột rỗng vào bảng sẽ làm CS tưởng số 0 là kết quả thật.

### 6.1 Amendment 2026-08-01 — Freshdesk CSAT được duyệt

Quyết định trên đúng với dashboard Langfuse-only tại thời điểm viết. PO sau đó
đã duyệt `2026-08-01-freshdesk-csat-integration-design.md`; spec đó là authority
cho ngoại lệ này:

- CSAT và outcome-reconciliation được đọc từ Freshdesk bằng CLI/job rời, không
  gọi Freshdesk khi phục vụ request dashboard.
- Bulk satisfaction ratings không được mở quyền; kiến trúc chính thức là fetch
  từng ticket có checkpoint và cache riêng tư.
- Mọi số Freshdesk nằm trong mục riêng, ghi rõ nguồn/thời điểm cập nhật; không
  tham gia gate P0 và không sửa AI First, reopen, outcome, TPE hay segment.
- Nội dung phản hồi survey chỉ được hiện sau redaction theo sáu điều kiện đã ký
  trong `PRODUCT.md`; nội dung gốc và conversation text không được serialize.

CSAT v11 dùng các định nghĩa bắt buộc sau:

- `response_count`: mọi survey response được gắn cho Admin CS ZaloPay trong
  cohort ticket đang xem.
- `ticket_count`: số Ticket ID khác nhau có ít nhất một response được duyệt.
- Response mới nhất của một ticket là max theo `(responded_at, response_key)`;
  ba bucket và breakdown outcome/Skill/Category đếm mỗi ticket đúng một lần.
- `feedback_entries` vẫn chứa mọi response có nội dung đã redact để điều tra;
  browser dùng từ “nội dung phản hồi”, không suy loại feedback.
- `TicketRow.csat_satisfaction` dùng cùng latest response; `unrated` chỉ dùng
  cho tuần đã fetch, còn tuần chưa fetch/cache vắng là `null`.
- Tuần cohort luôn lấy từ Langfuse ticket, không lấy từ `responded_at` survey.
- Mục `Khách hài lòng tới đâu` có selector `Tuần CSAT` ngay tại header, gồm
  từng tuần có dữ liệu và `Tất cả tuần`. Control này cập nhật cùng scope tuần
  dùng bởi segment, chẩn đoán và Ticket Explorer; không tạo một mẫu số CSAT cục
  bộ khác với phần còn lại của dashboard.

Outcome reconciliation v12 là chỉ báo quan sát riêng. Nó chỉ đọc metadata
conversation từ job ngoài serving process và chỉ tính public outgoing reply
sau bot của agent ID trong private roster PO duyệt. Requester/user và source 6
không được tính; unknown author là unresolved. Chỉ số này không viết lại AI
First hay outcome Langfuse.

Vì vậy câu “Không đưa cột Survey” vẫn áp cho bảng tuần Langfuse 14 cột: không
nhét số Freshdesk vào bảng đó. CSAT xuất hiện ở **mục riêng**, không phải cột
rỗng hay số 0 giả trong weekly report.

---

## 7. Quyền riêng tư

Ràng buộc cũ giữ nguyên: được hiện Ticket ID; cấm User ID, Trans ID, SĐT,
tên/email khách, nội dung hội thoại, prompt/response, raw payload và ID nội bộ
Langfuse.

**Ngoại lệ điều hướng hẹp do người dùng phê duyệt.** Frontend bundle và đúng
href sau được phép chứa project routing ID cố định, không phải secret:

```
https://langfuse.zalopay.vn/project/cmqubjzur000hz507ptubh2l9/traces?filter=sessionId%3BstringOptions%3B%3Bany%20of%3B{ticketId}&dateRange={fromMs}-{toMs}
```

Ngoại lệ này chỉ phục vụ link người dùng chủ động bấm trong ô Ticket. Nó không
cho phép serialize `traceId`, `observationId` hoặc bất kỳ giá trị Session ID
riêng nào khác. Filter grammar trong href được phép chứa literal `sessionId`;
giá trị filter `{ticketId}` dùng lại Ticket ID vốn đã được phép và cũng là
Langfuse session key theo contract hiện tại, không phải field mới lấy từ
Langfuse. `{fromMs}` là đầu ngày theo giờ Việt Nam của
`first_week_with_data`; `{toMs}` là cuối ngày theo giờ Việt Nam chứa
`snapshot.generated_at`. Custom range này ghi đè mặc định một ngày của bảng
Tracing mà không áp trần 90 ngày, nên vẫn bao phủ ticket cũ khi cửa sổ báo cáo
mở rộng. Project routing ID và hai URL điều hướng không được thêm vào
`/api/dashboard`, `/api/tickets`, snapshot, local storage hoặc CSV. Link được
tạo phía UI cho Ticket ID qua regex và không phát request ngoài khi tải trang;
navigation chỉ xảy ra sau click. Link Freshdesk tương ứng bị giới hạn ở origin
và path cố định:

```
https://vngzalopay.freshdesk.com/a/tickets/{ticketId}
```

Ngoài ngoại lệ literal project routing ID trong frontend bundle/href nói trên,
lệnh cấm ID nội bộ Langfuse vẫn giữ nguyên, không được diễn giải rộng hơn.

**Được phép ra browser** — đã kiểm từng giá trị: `App`, `Product Code`, `Kênh
thanh toán`, `Thông tin thêm.category`, `Thông tin thêm.sub_source`,
`skills_used`, guardrail `rule`, `escalation_guard_blocked`, và chỉ hai scalar
đã validate từ observation nguồn:
`output.result.transstatus`/`output.result.stepresult`.

Từ v14, các row aggregate của `transfer_reasons.triggers` còn được phép mang
enum `reason`, `source`, `stage`, skill label đã qua boundary validation và
`count`. Đây là projection tổng hợp; `traceId`, observation ID, raw input/output
và nội dung observation tuyệt đối không được đi cùng row.

Từ v15, TicketRow được phép mang duy nhất enum `transfer_reason` của trigger
đầu tiên để Explorer hiển thị cùng wording với bảng tổng hợp. Không đưa
`rule/source/stage/skill` cấp ticket ra browser.

`meta["Step result"]`, mọi chuỗi pipe và phần mô tả của nó bị cấm đi vào
snapshot/browser. Không được “sanitize” bằng cách tách một segment rồi coi đó
là Step result, vì đó vẫn là dùng sai nguồn.

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
| **P0** | `categories.py` đọc meta cho Category/App/Product Code; không đọc `meta["Step result"]`; `taxonomy.v2.json` + `off_topic` | Sửa đúng nguồn các thuộc tính ticket mà không đưa metadata legacy vào Step result |
| **P1** | Bỏ ràng buộc `turn == 0`; bỏ quarantine cuối tuần; `is_weekend_start`; `turn_count`; **lookback 14 ngày §3.4**; **sửa `scores.py`/`cli.py` cho compile §3.10** | Thu hồi ~35% ticket; lookback quyết định độ chính xác biên tuần |
| **P2** | Hai view tuần + weekly fields mới + gate viết lại + snapshot nền + migration | Cho bảng tuần đủ cột |
| **P3** | `iter_observations_by_name` + 7 lane enrichment song song, gồm TPE source và `output_guardrail`; suy giảm mềm | Thêm Intent/Skill/Guardrail/TPE đúng nguồn và giảm thời gian refresh |
| **P4** | Schema v6 (TPE nguồn từ v5 + same-period theo view) + packaged SPA theo §5 + cập nhật contract tests | Cần contract `(transstatus, step_result)` ổn định trước |
| **P5** | Mở rộng filter `/api/tickets` + Explorer + export | Hoàn thiện |

Sau **mỗi** giai đoạn: `.venv/bin/pytest -q` và `.venv/bin/python -m compileall -q src tests`.

### 8.1 Definition of done từng giai đoạn

| | Xong khi |
|---|---|
| P0 | Langfuse-only raw all-ticket: `ticket_count > 0`, `coverage_issue_category ≥ 0.90`, `coverage_tpe ≥ 0.85`, và `p0_pass` là AND của đúng hai flag; không source segment/entry point/presence filter được thu hẹp mẫu số; không còn giá trị `"other"`/`"unknown"` sinh ra từ keyword matching; fixture pipe trong `meta["Step result"]` không tạo Step result |
| P1 | `pytest` xanh, `compileall` xanh; `counts.weekend_start_count > 0` và ticket cuối tuần **có mặt** trong `sessions`; `counts.left_censored` giảm mạnh; `counts.pre_window_start` xuất hiện |
| P2 | Cả hai view qua invariant §3.9; service khởi động được với file snapshot v2 cũ trên đĩa |
| P3 | Observation TPE chỉ tạo cặp từ `output.result`; giá trị thiếu/không hợp lệ được xử lý theo §3.6; chặn enrichment endpoint → `"partial"` và snapshot vẫn dựng; refresh ≤ 2 phút |
| P4 | snapshot cũ bị bỏ qua và refresh thành v6; `same_period` nằm trong từng view; TPE table chỉ có bốn cột đã chốt; 1440px và 390px không overflow ngang; không console error; toggle cohort đổi số đúng và reset chart về `Tuần đủ`; theme lần đầu theo system, nút `Sáng`/`Tối` đổi đúng token + logo/Z và giữ preference sau reload; Copy dán Excel đúng cột; **①② nằm trọn above-the-fold ở 1440×900**; tóm tắt bằng lời (§5.7) sinh đúng cho cả template tuần đủ/WTD; `[Cách đọc]` và `[Xoá lọc]` hoạt động; tương phản ≥ 4.5:1 ở cả light/dark; đi hết trang bằng bàn phím, focus luôn thấy được; strict CSP không có `unsafe-inline`/`unsafe-eval` và không có external request |
| P5 | Mọi filter mới trả 422 với giá trị không có trong snapshot; test deny-list §7 xanh |

### 8.2 Chiến lược test không cần API thật

`tests/fixtures/traces.py` đã có sẵn — mở rộng ở đó, **không gọi mạng trong test**:

- Fixture trace phải chứa `input.other_info.meta` với **đúng key tiếng Việt có dấu** (`"Mã lỗi TPE"`, `"Thông tin thêm"`) — lỗi hay gặp là viết không dấu rồi test xanh nhưng prod hỏng.
- Ca biên bắt buộc: ticket không có `turn == 0`; ticket bắt đầu thứ Bảy;
  ticket có trace-đầu trước `complete_start_local` (kiểm lookback);
  `meta["Step result"]` dạng 1/4 segment đều bị bỏ qua; observation TPE có
  `stepresult` integer, numeric string, thiếu, `bool`, pipe, unicode lookalike
  và token quá dài; intent chỉ xuất hiện 1 lần (phải gộp `khác`); enrichment
  thiếu hoàn toàn.
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

### 9.3 Coverage dashboard kỳ vọng sau P0

| Chiều | Hiện tại | Kỳ vọng |
|---|---|---|
| Business không phải "Khác" | 54% | ≥ 95% (`issue_category`) |
| Transstatus có giá trị | Đo lại từ observation nguồn | Báo đúng coverage đo được, không bổ sung từ nguồn khác để đạt ngưỡng |
| Step result trong ticket chuyển CS | Đo lại từ observation nguồn | Hiển thị đủ tử số/mẫu số và số thiếu; không đặt mục tiêu giả |
| Guardrail rule | 98% | ≥ 98% (thêm `off_topic`) |

### 9.4 Kiểm chứng P0 Langfuse-only

Chạy aggregate-only từ root Langfuse trace, không observation, local overlay
hay artifact; không đưa credential lên argv:

```bash
.venv/bin/weekly-cs-report verify-dimensions --weeks 12 \
  --include-current-wtd --as-of 2026-07-31T10:00:00+07:00 --require-p0
```

Lệnh luôn in một JSON aggregate privacy-validated. Không có `--require-p0` thì
diagnostic giữ exit `0`; có flag thì exit `0` chỉ khi `p0_pass` đúng bằng
`true`, còn `p0_pass=false` in cùng JSON rồi exit `1`.

Observed raw-only diagnostic rerun cho fixed window trên cho kết quả:

```text
ticket_count = 6369
issue_category_present_count = 5393
coverage_issue_category = 0.8467577327680955
tpe_present_count = 5045
coverage_tpe = 0.7921180719108181
p0_issue_category_pass = false
p0_tpe_pass = false
p0_pass = false
```

Vì vậy exact expected exit của lệnh có `--require-p0` trên cùng current source
là `1`; verdict hiện tại là `p0_data=FAIL`, `go_live=BLOCKED`. Bằng chứng
diagnostic này chưa phải claim đã hoàn tất final current-source release rerun.
`coverage_tpe` P0 metadata không được dùng thay cho dashboard `coverage.tpe`,
Transstatus hay Step result.

### 9.5 Riêng tư, UI, hiệu năng

- **Riêng tư:** chạy test deny-list §7 trên snapshot thật; duyệt toàn bộ trang Ticket Explorer; grep response tìm SĐT/UUID/ID nội bộ.
- **UI:** Chrome 1440px và 390px — không overflow ngang toàn cục, bảng cuộn trong khung, không console error, toggle T2–T6/T2–CN đổi số đúng, click cột chart lọc toàn trang, Copy dán Excel đúng cột.
- **Hiệu năng:** đo wall-clock một lượt refresh đầy đủ, kỳ vọng ≤ 2 phút (hiện ~5 phút). Test suy giảm mềm: chặn observation endpoint, xác nhận snapshot vẫn dựng với `enrichment_status: "partial"`.

---

## 10. Việc ngoài phạm vi code

1. **Rotate `LANGFUSE_SECRET_KEY`** — Basic Auth từng xuất hiện trong process arguments. Cập nhật `.env`, giữ mode 0600.
2. Nếu cần diễn giải ý nghĩa `transstatus`/`stepresult`, mở một workstream có
   owner và tài liệu canonical riêng. Dashboard hiện tại cố ý chỉ hiển thị mã
   nguồn, không biến taxonomy chưa được xác nhận thành sự thật sản phẩm.
3. Chốt bộ nhãn §1.6 với CS trước khi phát hành. Chữ "AI cover" đang mang hai nghĩa trái ngược — không chốt thì mọi cuộc họp sẽ tranh cãi.
4. Đối soát §9.2 bước 3 với người giữ sheet.
5. Dashboard đang chạy ở `127.0.0.1:8765` là local service, không phải deployment production.
6. Docker chưa build/chạy được trên máy local (không có Docker runtime) — **không tuyên bố container đã kiểm chứng**.
7. Sau khi có bản P4, **ngồi cạnh 2 CS agent thật, giao một việc cụ thể** ("tìm ticket tuần trước quá 3 lượt xử lý mà chưa chuyển CS"), bấm giờ. Không hỏi "trông có đẹp không" — đo thời gian tới quyết định. Việc nào chặn thì sửa trước, phần thẩm mỹ tính sau.

---

## 11. Tham khảo

Nguyên tắc ở §5 lấy từ:

- [Geckoboard — Dashboard design best practices](https://www.geckoboard.com/resources/dashboard-design/) — góc trên-trái, phân cấp bằng kích thước, tỷ lệ data-ink, tránh pie/area, loại metric không hành động được, bối cảnh so sánh và ngưỡng cảnh báo.
- [DataCamp — Dashboard design tutorial](https://www.datacamp.com/tutorial/dashboard-design-tutorial) — quy trình 6 bước, quy tắc 10 giây, kim tự tháp ngược, cấu trúc thẻ KPI cố định, bốn lớp ngữ cảnh, giới hạn bảng màu, khả năng tiếp cận.
- [ThoughtSpot — Dashboard design examples & best practices](https://www.thoughtspot.com/data-trends/dashboard-design-examples-best-practices) — quy tắc tối đa 6 thành phần mỗi nhóm, 5–7 KPI chính, above-the-fold, mỗi tab trả lời một câu hỏi nghiệp vụ.
- [Nielsen Norman Group — Dashboards: making charts and graphs easier to understand](https://www.nngroup.com/articles/dashboards-preattentive/) — xếp hạng tiền chú ý (độ dài > vị trí 2D > diện tích > góc), loại bỏ pie/treemap/gauge/3D, không dùng màu đơn thuần.
- Kinh nghiệm thực chiến BI (sản xuất, y tế, cải tiến dịch vụ) — bắt đầu từ *quyết định* chứ không từ dữ liệu (§5.1); điều hướng giống website cho người không rành kỹ thuật (§5.6); tiêu đề động và tóm tắt bằng lời (§5.7); **nói thật về chất lượng dữ liệu đầu vào** (§5.13); "phù hợp với người đọc" thay vì "đơn giản nhất có thể" (§5.1).
