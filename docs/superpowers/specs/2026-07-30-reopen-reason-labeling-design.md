# Spec — Lớp gán nhãn lý do reopen (mở khoá V2)

> Trạng thái: **đã chốt design, sẵn sàng implement**. Người viết spec: Claude. Người implement: Codex (GPT 5.6).
> Ngày: 2026-07-30. Dựa trên codebase `langfuse-weekly-cs-report` hiện tại.
> Quan hệ với tài liệu khác: đây là hiện thực hoá **V2** đã khai báo tại
> `docs/superpowers/specs/2026-07-29-langfuse-weekly-cs-dashboard-design.md:44-60`.
> Không thay thế `docs/SPEC-v2.md`. Khi mâu thuẫn về metric deterministic đang có, SPEC-v2 và V1 thắng.

---

## 0. Vấn đề

Dashboard trả lời được *bao nhiêu* và *ở nhóm nào*. Không trả lời được *vì sao*.

`reopen_within_7d` dao động 16–29% mỗi tuần và là con số xấu nhất trên dashboard. Nó gộp chung nhiều nguyên nhân dẫn tới **những hành động khác hẳn nhau** của PO:

- AI trả lời sai nội dung → sửa skill
- AI trả lời đúng nhưng chung chung, không giải quyết → sửa cách trả lời, thêm tool tra cứu
- Vấn đề chưa xử lý xong, khách hỏi tiến độ → vấn đề SLA/backend, không phải skill
- Khách hỏi việc khác → **không phải lỗi**, đang bị tính vào mẫu số
- Khách không chấp nhận kết quả → vấn đề chính sách, skill không sửa được

Gộp thành một cột 26% thì không quyết được gì. Spec này thêm **một chiều dữ liệu**: *lý do reopen*.

Lý do nằm trong nội dung hội thoại — thứ dashboard cố ý chặn khỏi browser. Đây là công việc duy nhất trong hệ thống **bắt buộc phải dùng LLM**: biến free text thành nhãn có cấu trúc, server-side, chỉ lưu nhãn chứ không lưu text.

### 0.1 Năm điều kiện mở khoá V2

Spec dashboard chặn V2 cho tới khi đủ năm thứ. Đối chiếu:

| Điều kiện (spec V1, dòng 52-58) | Thoả ở mục nào |
|---|---|
| an approved PII handling route | §4 |
| a fixed and versioned output taxonomy | §2 |
| a manually labelled evaluation set of ~50 tickets | §5 GĐ 3 — spec này dùng **200**, vượt yêu cầu |
| accuracy and abstention thresholds | §5 GĐ 4 |
| evidence links for every suggested label | §4.2 |

Và giữ nguyên ràng buộc dòng 60: **nhãn AI là gợi ý, không thay thế metric V1.** Không metric deterministic nào bị lớp này sửa đổi.

### 0.2 Ngoài phạm vi

- Phân loại `unusually long conversations` và `transfer reasons unknown` — cũng thuộc V2, dùng lại được module này, **không nằm trong spec này**.
- Vá `taxonomy.v2.json` từ ô "Không xác định".
- Mọi thay đổi lên metric deterministic đang công bố.

---

## 1. Định nghĩa tập dữ liệu

### 1.1 Tập gán nhãn

Session thoả **tất cả**:

| Điều kiện | Nguồn |
|---|---|
| `ai_first == True` | `classification.py:243` |
| `reopen_within_7d == 1` | `classification.py:260` |
| `outcome in {"ai_end_to_end", "ai_then_cs"}` | `classification.py:245` |
| `data_quality == "valid"` | `classification.py:246` |

**Dùng `reopen_within_7d`, không dùng `reopen_lifetime`.** Lifetime tăng mãi theo thời gian trôi nên tuần cũ và tuần mới không so được — vô dụng cho xu hướng.

Session có `cohort_status == "weekend_start"` bị loại (vì `outcome is None`, `classification.py:231-232`). Số bị loại **phải đếm và hiện ra**, không được loại im lặng.

Mỗi session gán nhãn **đúng một lần**, kể cả khi reopen nhiều lượt. Không thì nhóm khách dai dẳng chiếm hết dữ liệu.

### 1.2 Nhóm đối chứng — bắt buộc

Phải đo tỉ lệ reopen của `direct_cs` (AI chưa trả lời gì) đặt cạnh tỉ lệ của nhóm AI-first.

Lý do: nếu `direct_cs` cũng reopen ~26% thì reopen **không phải vấn đề của AI**, nó là đặc tính của loại ticket này. Không có nhóm đối chứng thì mọi kết luận "AI làm khách quay lại" đều không kiểm chứng được.

Nhóm đối chứng **chỉ đo tỉ lệ, không gán nhãn**. Chi phí bằng không.

### 1.3 Ràng buộc khi thêm nhóm đối chứng

`classification.py:266-268` đặt `reopen_lifetime = None` và `reopen_within_7d = None` khi `ai_first == False`. `cli.py:253-261` lọc `is not None` để tính tỉ lệ đang công bố.

**Cấm sửa ngữ nghĩa hai trường đó.** Thêm `direct_cs` vào chúng sẽ làm tỉ lệ reopen đang công bố đổi ngay lập tức, không ai nhận ra.

Thêm trường mới trên `SessionMetrics`:

```python
control_reopen_within_7d: int | None
# = 1/0 khi outcome == "direct_cs" và turn0 hợp lệ
# = None với mọi outcome khác
```

Công thức giống hệt `reopen_within_7d` (`timedelta() < followup.timestamp - turn0.timestamp <= 168h`, `classification.py:260-265`), chỉ khác điều kiện kích hoạt.

Test bắt buộc: chạy pipeline trên fixture hiện có, khẳng định `reopen_7d_rate`, `reopen_7d_denominator`, `reopen_lifetime_rate` **không đổi giá trị**.

---

## 2. Danh sách nhãn

### 2.1 Nguyên tắc

Danh sách **cố định, có version**, không để model tự sinh cụm mỗi tuần.

Lý do: mục đích của dashboard là xu hướng theo thời gian. Cụm tự sinh đổi ranh giới mỗi lần chạy → không vẽ được đường xu hướng. Và cụm tự do không test được; danh sách cố định thì dựng được golden set.

Tiêu chí gộp nhãn: **hai nhãn dẫn tới cùng một hành động của PO thì gộp làm một.** Nhãn tồn tại để quyết định, không để mô tả. Nhắm 5–7 nhãn.

### 2.2 File config

`config/reopen_labels.v1.json`, cùng nếp version với `taxonomy.v1/v2.json`:

```json
{
  "version": "v1",
  "created_at": "2026-07-30",
  "labels": [
    {
      "key": "ai_wrong_content",
      "display": "AI trả lời sai nội dung",
      "definition": "Câu trả lời của AI chứa thông tin sai so với thực tế giao dịch hoặc chính sách.",
      "po_action": "sửa skill"
    }
  ],
  "abstain_label": "other",
  "requires_quote": ["other"]
}
```

**Nội dung `labels` do PO chốt ở Giai đoạn 1 (§5), không phải Codex tự nghĩ.** Codex implement phần đọc file và ràng buộc schema. File khởi tạo `labels: []` và code phải fail rõ ràng khi danh sách rỗng.

`other` là **nhãn từ chối phân loại (abstention)**, luôn tồn tại, bắt buộc kèm trích dẫn.

### 2.3 Đổi version

Đổi danh sách = tạo `reopen_labels.v2.json`, không sửa đè v1. Snapshot ghi `labels_version` theo từng tuần để dashboard đánh dấu mốc, tránh so nhầm hai bên mốc.

---

## 3. Kiến trúc

Bốn module mới, tách rời, test độc lập được.

| Module | Việc | Phụ thuộc |
|---|---|---|
| `reopen_population.py` | dựng tập §1.1, khử trùng lặp, tính tỉ lệ đối chứng §1.2 | `models.py`, `classification.py` |
| `reopen_sampling.py` | embed tin nhắn quay lại, gom cụm, phân tầng, xuất mẫu | `reopen_population` |
| `content_labeler.py` | gọi model, structured output, chỉ nhận nhãn trong danh sách, cache theo session | `config/reopen_labels.v*.json` |
| `llm_client.py` | vỏ bọc API: retry, timeout, đếm token, chế độ fake cho test | — |

Mở rộng file có sẵn:

| File | Thay đổi |
|---|---|
| `models.py` | thêm `control_reopen_within_7d` vào `SessionMetrics`; thêm dataclass `ReopenLabel` |
| `classification.py` | tính `control_reopen_within_7d` (§1.3) |
| `pipeline.py` | sau khi tổng hợp xong, chạy labeler trên tập §1.1 |
| `dashboard_schema.py` | chiều mới: đếm theo nhãn × tuần × domain × outcome |
| `cli.py` | lệnh mới `sample-reopen`, `sample-golden`, `eval-labels`; tỉ lệ đối chứng vào `summary.json` |
| `static/index.html` | hiển thị chiều mới kèm độ phủ |

### 3.1 Tin nhắn dùng để gán nhãn

Lý do reopen nằm ở **tin nhắn khách gửi khi quay lại**, không phải cả ticket.

Đầu vào mỗi session, đúng ba đoạn:

1. `input` của trace `turn == 0` — khách hỏi gì ban đầu
2. `output` của trace `turn == 0` — AI trả lời gì
3. `input` của **followup đầu tiên trong 168h** — khách nói gì khi quay lại

Cả ba đã mask PII. Không gửi toàn bộ hội thoại — vừa đắt vừa loãng tín hiệu.

Hệ quả kỹ thuật: labeler **phải chạy trong lượt pipeline** khi payload còn trong bộ nhớ. Artifact không chứa raw payload (`README.md`: *"Raw trace and observation payloads are never serialized"*) nên không chạy lại từ artifact được.

---

## 4. Ranh giới PII

Đây là lần đầu hệ thống **gửi nội dung hội thoại ra dịch vụ ngoài**. Phần này chặt nhất. Nó là "approved PII handling route" mà V1 đòi hỏi.

### 4.1 Quy tắc

| Quy tắc | Bắt buộc |
|---|---|
| Text đọc server-side, mask trước khi gọi API | có |
| Snapshot dashboard chỉ chứa `session_id → label` + số đếm | có |
| Snapshot **không** chứa bất kỳ trường text tự do nào | có |
| Trích dẫn cho nhãn `other` ghi vào artifact server-side mode `600` | có |
| Trích dẫn **không** ra browser, **không** vào snapshot | có |
| Prompt và response không ghi log | có |

### 4.2 Cách mask — tất định, không heuristic

**Cấm nhận diện tên bằng heuristic hay NER.** Không có cách nhận diện tên tiếng Việt nào đủ tin cậy, và đoán sai ở đây là rò PII thật. Dùng đúng hai cơ chế tất định:

**a) Thay thế theo giá trị đã biết.** Với mỗi session, `other_info.meta` đã chứa sẵn giá trị PII của chính khách đó (`docs/SPEC-v2.md §1.1`): `UserID`, `App user`, `TransID`, `Số điện thoại người dùng`. Lấy đúng các chuỗi đó, tìm-và-thay trong free text. Khách tự gõ số điện thoại hoặc tên mình vào nội dung vẫn bị bắt, vì giá trị đã có trong meta. Không suy đoán một ký tự nào.

**b) Mask theo lớp mẫu.** Dãy 9–20 chữ số, email, URL, số thẻ. Các lớp này có mẫu xác định, không phải suy đoán ngữ nghĩa.

**Rủi ro còn lại — chấp nhận có điều kiện.** Tên người thứ ba do khách gõ trong nội dung (ví dụ tên người nhận tiền) mà không có trong meta thì **không được mask**. Đây là quyết định của PO và bộ phận bảo mật, không phải của người implement. Giảm thiểu bắt buộc: cắt free text ở độ dài trần; gateway phải là gateway nội bộ công ty.

**Cổng bắt buộc trước lần gọi API thật:** chạy masker trên 200 đoạn text, xuất file server-side mode `600`, **PO đọc bằng mắt và ký duyệt**. Không có chữ ký này thì không được gọi API lần nào. Đây chính là "approved PII handling route" mà V1 đòi hỏi.

### 4.3 Evidence — server-side, không ra browser

V1 đòi *"evidence links for every suggested label"*. Điều kiện là evidence **tồn tại và truy được**, không đòi nó nằm trong browser.

Vì `docs/SPEC-v2.md §7` cấm đưa ID nội bộ Langfuse ra browser, evidence **nằm hoàn toàn ở artifact server-side** mode `600`:

| Nơi | Chứa gì |
|---|---|
| Snapshot (browser) | chỉ số đếm theo nhãn, độ phủ, tỉ lệ đối chứng |
| Artifact server-side `600` | `session_id`, `label`, anchor trace ID, follow-up trace ID, trích dẫn đã mask (chỉ nhãn `other`) |

**Không nới validator PII, không allowlist ngoại lệ, không test ngoại lệ.** Ranh giới §7 giữ nguyên tuyệt đối.

### 4.4 Test bắt buộc

Quét toàn bộ snapshot đã sinh, khẳng định mọi giá trị chuỗi nằm trong tập enum đã khai báo. Không chuỗi tự do, không trace ID, không session ID nào lọt ra snapshot.

---

## 5. Ba giai đoạn — người và máy xen kẽ

Thứ tự bắt buộc. Codex làm GĐ 0, 2, 4. **PO làm GĐ 1 và 3. Codex không được làm thay.**

```
[GĐ 0 · Codex]  population + sampling + LLM sinh lý do tự do
       ↓
[GĐ 1 · PO]     đọc 150-300 lý do, gom thành 5-7 nhãn → reopen_labels.v1.json
       ↓                                      ↘
[GĐ 2 · Codex]  classifier + schema           [GĐ 3 · PO]  gán tay 200 ticket ngẫu nhiên
       ↓                                      ↙
[GĐ 4 · Codex]  đo độ khớp → đạt ngưỡng → bật lên dashboard
```

### GĐ 0 — Lấy mẫu discovery

Lệnh mới, read-only, không ghi snapshot:

```bash
weekly-cs-report sample-reopen --weeks 4 --out artifacts/reopen_discovery/
```

Các bước:

1. Dựng tập §1.1 trên 4 tuần gần nhất
2. Embed **chỉ tin nhắn khách gửi khi quay lại** (đoạn 3 của §3.1), toàn bộ tập
3. Gom cụm, `k ∈ [5, 15]`, chọn k theo silhouette
4. Phân tầng lấy mẫu theo bốn trục: **tuần × domain × outcome × cluster**
5. Mỗi mẫu, gọi model sinh **một câu lý do tự do** (chưa có nhãn)
6. Xuất `artifacts/reopen_discovery/reasons.csv`: `session_id, week, domain, outcome, cluster_id, reason_text`

**Bẫy phải né ở bước 2.** Embed cả ticket thì cụm sinh ra sẽ theo **domain** (IBFT / nạp tiền / rút tiền), không theo lý do — tín hiệu mạnh nhất trong text ticket là sản phẩm. Chiều domain đã có sẵn từ metadata; cụm như thế vô dụng.

**Vai của cluster: khung phân tầng để lấy mẫu, KHÔNG phải danh sách nhãn.** Cụm máy sinh không gắn với hành động của PO, mà tiêu chí gộp nhãn là hành động.

**Cỡ mẫu — không tính bằng công thức thống kê.** Lấy theo lô 50, dừng khi hai lô liên tiếp không sinh lý do mới. Thực tế 150–300. Đây là bão hoà: mục tiêu là **phủ hết các loại**, không phải ước lượng tỉ lệ.

Mẫu discovery **được phép lệch tần suất**. Tần suất thật lấy từ GĐ 4 (gán nhãn 100% tập). Nhóm chiếm 3% mà bốc ngẫu nhiên 100 cái thì trung bình chỉ dính 3 — quá ít để nhận ra là nhóm riêng. Phân tầng để cứu chỗ đó.

### GĐ 1 — PO chốt danh sách nhãn *(người làm)*

PO đọc `reasons.csv`, gom thành 5–7 nhãn theo §2.1, ghi vào `config/reopen_labels.v1.json`.

Codex dừng, chờ file có nội dung.

### GĐ 2 — Classifier

```python
def label_session(session: ReopenSession, labels: LabelSet) -> ReopenLabel
```

- structured output, enum đúng bằng `labels.keys() + [abstain_label]`
- nhãn ngoài danh sách → loại, đếm `invalid`, **không im lặng nuốt**
- `other` không kèm trích dẫn → cũng tính `invalid`
- cache theo `session_id`; đã gán rồi thì không gọi lại
- tỉ lệ `invalid` tăng là tín hiệu prompt/model trôi → hiện lên dashboard

Ở GĐ này chiều mới tính ra nhưng **chưa hiện lên dashboard**.

### GĐ 3 — Golden set *(người làm, song song GĐ 2)*

```bash
weekly-cs-report sample-golden --n 200 --out artifacts/reopen_golden/
```

- **ngẫu nhiên thuần, KHÔNG phân tầng.** Phân tầng thì độ khớp đo được không phản ánh dữ liệu thật
- **khác tập discovery.** Đo model trên chính dữ liệu đã dùng để nghĩ ra nhãn thì luôn đẹp giả tạo
- trộn ~30 cặp lặp lại (cùng session xuất hiện hai lần, PO không biết) → đo **độ tự nhất quán của người**. PO tự mâu thuẫn 15% thì đòi model khớp 95% là vô lý. Con số đó là **trần** của bài toán
- file xuất **không chứa nhãn model sinh ra**. PO gán xong trước khi nhìn output model, nếu không thì bị mỏ neo và số đo vô nghĩa

200 mẫu vượt mức ~50 mà V1 yêu cầu; giữ 200 vì có 5–7 nhãn, 50 mẫu không đủ để đo từng nhãn riêng.

### GĐ 4 — Đo và bật

```bash
weekly-cs-report eval-labels --golden artifacts/reopen_golden/ --labels config/reopen_labels.v1.json
```

**Định nghĩa metric — chốt, không được tự diễn giải khác:**

| Khái niệm | Định nghĩa chính xác |
|---|---|
| Tập tính metric model | Golden set **sau khi khử bản lặp ẩn**, giữ bản xuất hiện đầu. Mẫu số = 200 − số bản lặp |
| Bản lặp ẩn dùng làm gì | **Chỉ** để tính độ tự nhất quán của người. Không vào mẫu số của model |
| Accuracy tổng | Tỉ lệ khớp thuần trên tập đã khử lặp |
| Accuracy từng nhãn | **Recall theo nhãn thật của PO**: mẫu số = số ticket PO gán nhãn X; tử = model cũng gán X |
| Vì sao recall, không phải precision | Thất bại đáng sợ là **một nguyên nhân thật bị tàng hình** trên dashboard → PO không hành động. Precision vẫn tính và in ra làm chẩn đoán, nhưng không dùng làm cổng |
| Nhãn có support < 10 | Đánh dấu `unverified`, **loại khỏi cổng**, in rõ ra output. Không tính là trượt |
| Bắt buộc in kèm | Ma trận nhầm lẫn, để thấy cặp nhãn nào đang nhập nhằng |

Ngưỡng nhận, cả ba phải đạt:

| Ngưỡng | Giá trị | Ý nghĩa |
|---|---|---|
| Accuracy tổng | ≥ 80% | trên tập đã khử lặp |
| Recall từng nhãn (support ≥ 10) | ≥ 60%, không nhãn nào thấp hơn | chặn trường hợp một nhãn đông kéo tổng lên |
| Abstention (`other`) | ≤ 15% tập golden | cao hơn nghĩa là danh sách nhãn chưa phủ thực tế |

**Điều kiện tiên quyết trước khi đánh giá model:** độ tự nhất quán của người ≥ 85%. Thấp hơn thì **không đánh giá model** — danh sách nhãn mới là thứ hỏng, quay lại GĐ 1. Đo model trên nhãn mà chính người ra nhãn còn tự mâu thuẫn thì con số vô nghĩa.

Không đạt ngưỡng: nhãn thấp lè tè thường là **nhãn định nghĩa mơ hồ** — sửa danh sách, đừng đổ cho model. Abstention cao cũng là tín hiệu thiếu nhãn, không phải model kém.

Đạt: bật chiều mới vào pipeline tuần và lên dashboard.

---

## 6. Chi phí

| Khoản | Lượng | Ghi chú |
|---|---|---|
| Gán nhãn | ~1.300 session/tháng | mỗi session **một lần**, cache theo `session_id`; tuần sau chỉ xử lý session mới |
| Input mỗi lượt | 3 đoạn ngắn đã mask | không gửi cả hội thoại |
| Output mỗi lượt | vài token | enum + trích dẫn khi `other` |
| Embedding | toàn bộ tập reopen | rẻ hơn gán nhãn một bậc |
| Tool call | không | labeler không gọi tool |

**Không chạm traffic production.** Chạy sau, theo lô, trên ~26% dữ liệu.

Cấu hình qua biến môi trường, không hardcode:

```
OPENAI_API_KEY        # từ secret store đã duyệt, không vào repo, không vào log
OPENAI_BASE_URL       # gateway công ty
OPENAI_LABEL_MODEL    # model rẻ có structured output
OPENAI_EMBED_MODEL
```

Codex **phải xác nhận tên model khả dụng trên gateway công ty** trước khi đặt mặc định. Không đoán tên model.

---

## 7. Xử lý lỗi

**Nguyên tắc cứng: lớp gán nhãn hỏng KHÔNG được làm hỏng dashboard đang chạy.**

| Tình huống | Hành vi |
|---|---|
| API không truy cập được | chiều mới `status: unavailable`; mọi metric deterministic giữ nguyên |
| Hết quota | như trên, mã lỗi cố định, không lộ chi tiết credential |
| Timeout một session | bỏ session đó, đếm `failed`, tiếp tục phần còn lại |
| Model trả nhãn ngoài danh sách | đếm `invalid`, không nuốt |
| `config/reopen_labels.*.json` rỗng hoặc thiếu | fail rõ ràng lúc khởi động, không chạy nửa vời |

Theo đúng nếp last-good snapshot đã có (`README.md`: *"a failed read keeps the last-good data and exposes only a fixed error code"*).

---

## 8. Schema snapshot

Thêm vào snapshot, theo từng tuần:

```json
{
  "reopen_reason": {
    "labels_version": "v1",
    "status": "labeled",
    "counts": {
      "ai_wrong_content": {"ai_end_to_end": 42, "ai_then_cs": 8},
      "other": {"ai_end_to_end": 11, "ai_then_cs": 2}
    },
    "by_business": {"ibft": {"ai_wrong_content": 30}},
    "coverage": {
      "population": 340,
      "labeled": 331,
      "abstained": 13,
      "failed": 4,
      "invalid": 5,
      "skipped_weekend_start": 12
    },
    "control": {
      "direct_cs_reopen_7d_rate": 0.244,
      "direct_cs_denominator": 1203
    }
  }
}
```

`status` nhận `labeled` | `pending` | `unavailable`.

Ràng buộc: **snapshot chỉ chứa số đếm và enum.** Không text tự do, không trace ID, không session ID. Bảng evidence theo session nằm ở artifact server-side mode `600` (§4.3).

`coverage` **phải hiện lên UI**. Chiều dữ liệu không kèm độ phủ thì người đọc không biết nó đại diện cho bao nhiêu phần của tập.

UI phải ghi rõ chiều này là **nhãn do model gợi ý**, phân biệt thị giác với metric deterministic — theo ràng buộc V1 dòng 60.

---

## 9. Test

| Test | Kiểm gì |
|---|---|
| `test_reopen_population.py` | tập §1.1 đúng; khử trùng lặp session; đếm `skipped_weekend_start` |
| `test_reopen_control.py` | `control_reopen_within_7d` đúng; **`reopen_7d_rate`, `reopen_7d_denominator`, `reopen_lifetime_rate` không đổi** |
| `test_content_labeler.py` | LLM giả: schema đúng; cache hoạt động; **từ chối nhãn ngoài danh sách**; `other` thiếu trích dẫn → `invalid` |
| `test_reopen_sampling.py` | mọi ô (tuần × domain × outcome) có mẫu; embed đúng tin nhắn quay lại, không phải cả ticket |
| `test_reopen_pii.py` | snapshot không chứa chuỗi tự do, trace ID, session ID; evidence và trích dẫn chỉ ở artifact mode `600` |
| `test_masker.py` | giá trị meta (`UserID`, `App user`, `TransID`, số điện thoại) bị thay hết trong free text; dãy số/email/URL bị mask; **không có nhánh nhận diện tên bằng heuristic** |
| `test_eval_labels.py` | khử bản lặp trước khi tính; recall theo nhãn thật; nhãn support < 10 ra `unverified` chứ không trượt; người tự nhất quán < 85% → từ chối đánh giá |
| `test_reopen_failure.py` | API hỏng → `status: unavailable`, metric deterministic nguyên vẹn |
| `test_dashboard_schema.py` (mở rộng) | khối `reopen_reason` đúng schema |

`eval-labels` chạy offline, **không nằm trong CI** (cần API thật).

Toàn bộ test dùng LLM giả. Không test nào gọi API thật.

---

## 10. Thứ tự implement

1. `control_reopen_within_7d` + test khẳng định số cũ không đổi *(độc lập, làm ngay được)*
2. Masker (§4.2) + `test_masker.py`. **Phải xong trước mọi lần gọi API.**
3. `llm_client.py` + chế độ fake
4. `reopen_population.py` + test
5. `reopen_sampling.py` + lệnh `sample-reopen`
6. **DỪNG — cổng PII: xuất 200 đoạn đã mask, PO đọc và ký duyệt (§4.2).** Chưa ký thì không gọi API lần nào
7. Chạy `sample-reopen` thật → `reasons.csv`
8. **DỪNG — chờ PO chốt `config/reopen_labels.v1.json`**
9. `content_labeler.py` + test
10. Lệnh `sample-golden` *(PO gán tay song song bước 9)*
11. Mở rộng `dashboard_schema.py` + `pipeline.py`, chạy chế độ shadow — tính ra nhưng chưa lên UI
12. Lệnh `eval-labels`
13. **DỪNG — chờ độ tự nhất quán của người ≥ 85% và cả ba ngưỡng §5 GĐ 4 đạt**
14. Bật labeling trong refresh tuần **và** hiện chiều mới lên `static/index.html`

Ba điểm dừng ở bước 6, 8 và 13 là bắt buộc. Bỏ qua thì hoặc gửi PII chưa ai duyệt ra ngoài, hoặc sinh ra một chiều dữ liệu không ai kiểm chứng — đúng thứ mail của head of product cấm: *"A confident wrong answer is worse than no answer."*
