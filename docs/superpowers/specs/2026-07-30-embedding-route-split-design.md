# Spec — Tách đường embedding khỏi đường label

> Trạng thái: **chờ implement**. Người viết spec: Claude. Người implement: Codex (GPT 5.6 sol).
> Ngày: 2026-07-30.
> Quan hệ: **phụ lục** của `specs/2026-07-30-reopen-reason-labeling-design.md` — sửa §3 (bảng module) và §10 bước 3. Không đổi bất cứ điều gì khác trong spec đó: taxonomy, ngưỡng, ba điểm dừng, ranh giới PII giữ nguyên tuyệt đối.

---

## 0. Vấn đề

`LLMSettings.from_environment()` (`llm_client.py:52-69`) đòi **một** `base_url` + **một** `api_key` dùng chung cho cả label model lẫn embed model. Giả định đó đã sai với hạ tầng thật.

Đo được ngày 2026-07-30:

| Gateway | Chat | Embeddings |
|---|---|---|
| `https://vllm.zalopay.vn/v1` | **200 OK**, `gemma-3-27b` trả lời thật, không cần key | `400 "The model does not support Embeddings API"` |
| `https://vllm.zalopay.vn/v1/models` | chỉ 1 model: `gemma-3-27b` | không có model embedding nào |
| `https://api.openai.com/v1` | `401 insufficient_quota` (key hợp lệ, tài khoản chưa có quota) | cùng lỗi |
| `https://litellm.zalopay.vn/v1` | `401` — đòi virtual key `sk-...`, key hiện có không đúng dạng | chưa kiểm được |
| `https://router.huggingface.co/hf-inference/models/<model>/pipeline/feature-extraction` | — | `401` (route tồn tại, chỉ thiếu token) |

Kết luận: label route và embed route **bắt buộc nằm trên hai host khác nhau**. Không phải lựa chọn thiết kế, là ràng buộc hạ tầng.

---

## 1. Model embedding đã chọn

**`intfloat/multilingual-e5-base`** — 768 chiều, đa ngữ, hỗ trợ tiếng Việt tốt.

Đo thật ngày 2026-07-30 bằng HF token (scope Read), endpoint `pipeline/feature-extraction`:

| Model | Kết quả | Chiều |
|---|---|---|
| `hiieu/halong_embedding` (lựa chọn đầu) | **`"Model not supported by provider hf-inference"`** | — |
| `intfloat/multilingual-e5-base` | **OK**, `depth=2` | 768 |
| `intfloat/multilingual-e5-large` | OK, `depth=2` | 1024 |
| `BAAI/bge-m3` | OK, `depth=2` | 1024 |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | OK, `depth=2` | 384 |

Lưu ý về cách đo: gọi **không token** thì cả 5 model đều trả `401`, dễ tưởng là đều dùng được. Chỉ khi có token mới lộ ra `halong_embedding` không được serve. Không được suy ra "model khả dụng" từ mã `401`.

Lý do chọn `multilingual-e5-base`:

- `halong_embedding` (tune riêng tiếng Việt, ưu tiên đầu) **finetune từ chính model này** → đây là lựa chọn thay thế gần nhất trong số model được serve.
- 768 chiều, cân bằng; không cần `e5-large`/`bge-m3` (1024 chiều, nặng hơn) vì mục đích chỉ là **khung phân tầng lấy mẫu** (spec gốc §GĐ 0: *"Vai của cluster: khung phân tầng để lấy mẫu, KHÔNG phải danh sách nhãn"*).
- Không chọn `dangvantuan/vietnamese-embedding` (PhoBERT thuần Việt): ticket CS lẫn mã lỗi, tên bank, chuỗi tiếng Anh — model thuần Việt yếu ở phần đó. (Chưa kiểm model này có được serve hay không.)

**Quy ước prefix của dòng e5:** model e5 được train với tiền tố `"query: "` / `"passage: "`. Cho việc gom cụm, thêm `"query: "` vào **mọi** text một cách nhất quán trước khi gửi. Bỏ prefix làm chất lượng vector giảm mà không có lỗi nào báo ra.

## 2. Contract biến môi trường

Đã ghi sẵn vào `.env` (mode `600`). Codex implement đúng theo tên này, không tự đổi:

```dotenv
# Label route — giữ nguyên 4 biến OPENAI_* đang có
OPENAI_API_KEY="not-required"          # vLLM tự host không kiểm key, SDK chỉ cần chuỗi khác rỗng
OPENAI_BASE_URL="https://vllm.zalopay.vn/v1"
OPENAI_LABEL_MODEL="gemma-3-27b"
OPENAI_EMBED_MODEL="unused-see-EMBED_MODEL"

# Embed route — mới
EMBED_PROVIDER="hf"                     # "hf" | "openai"
EMBED_BASE_URL="https://router.huggingface.co/hf-inference/models"
EMBED_MODEL="hiieu/halong_embedding"
EMBED_API_KEY=                          # HF token scope Read
```

`OPENAI_EMBED_MODEL` giữ lại để không phá kiểm tra "đủ 4 biến" hiện có, nhưng khi `EMBED_PROVIDER != "openai"` thì **không được dùng**. Giá trị `"unused-see-EMBED_MODEL"` là cố ý, để ai đọc log cũng biết ngay.

## 3. Thay đổi code

### 3.1 `LLMSettings`

Tách thành hai cấu hình, giữ `LLMSettings` là mặt tiền:

```python
@dataclass(frozen=True)
class EmbedSettings:
    provider: str        # "hf" | "openai"
    base_url: str
    model: str
    api_key: str

@dataclass(frozen=True)
class LLMSettings:
    api_key: str         # label route, như cũ
    base_url: str        # label route, như cũ
    label_model: str
    embed_model: str     # giữ để tương thích, KHÔNG dùng khi embed.provider != "openai"
    embed: EmbedSettings
```

`from_environment()`:

- 4 biến `OPENAI_*` vẫn bắt buộc, thiếu → `LLMConfigurationError` (không đổi hành vi cũ).
- Đọc thêm `EMBED_PROVIDER`, `EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_API_KEY`.
- `EMBED_PROVIDER` vắng → mặc định `"openai"`, `EmbedSettings` lấy y nguyên giá trị `OPENAI_*` (tương thích ngược, test cũ không vỡ).
- `EMBED_PROVIDER` có giá trị ngoài `{"hf","openai"}` → `LLMConfigurationError`.
- `EMBED_PROVIDER == "hf"` mà thiếu `EMBED_BASE_URL`/`EMBED_MODEL`/`EMBED_API_KEY` → `LLMConfigurationError`.

### 3.2 Implementation `embed()`

`llm_client.py:110` đã là `Protocol`, `:322` là implementation OpenAI. Thêm nhánh HF, **không sửa nhánh OpenAI**.

Request HF:

```
POST {EMBED_BASE_URL}/{EMBED_MODEL}/pipeline/feature-extraction
Authorization: Bearer {EMBED_API_KEY}
Content-Type: application/json
{"inputs": ["text 1", "text 2", ...], "options": {"wait_for_model": true}}
```

Response là mảng lồng. **Hai dạng có thể xảy ra, phải xử lý cả hai:**

| Dạng | Nghĩa | Xử lý |
|---|---|---|
| `[[f, f, ...], [f, f, ...]]` — 2 chiều | đã pooling sẵn, mỗi input một vector | dùng trực tiếp |
| `[[[f,...], [f,...]], ...]` — 3 chiều | token-level, chưa pooling | **mean-pool theo chiều token** |

**Đã đo thật:** `multilingual-e5-base` trả `depth=2`, shape `[2, 768]` cho 2 input — tức **đã pooling sẵn**, đi nhánh trực tiếp. Bốn model khác trong bảng §1 cũng đều `depth=2`.

Vẫn phải viết cả hai nhánh: nếu sau này đổi `EMBED_MODEL` sang model không có cấu hình pooling thì response thành 3 chiều, và **sai giả định ở đây cho ra vector rác mà không báo lỗi** — k-means vẫn chạy bình thường trên rác. Đếm số chiều rồi rẽ nhánh, đừng hardcode.

Ràng buộc bắt buộc:

- Mọi vector phải cùng số chiều; lệch → raise `LLMServiceError`.
- Số vector trả về phải bằng số input; lệch → raise (`_normalized_vectors` ở `reopen_sampling.py:190` đã kiểm, nhưng kiểm sớm ở client cho lỗi rõ hơn).
- HF trả `503` hoặc model đang load → dùng cơ chế retry hiện có, cấu hình như label route.
- Batch: HF Inference giới hạn payload; chia lô **≤ 64 input mỗi request**, ghép kết quả theo đúng thứ tự đầu vào.
- `LLMUsage`: HF không trả token count. Đặt `input_tokens=0, output_tokens=0, total_tokens=0` và **ghi rõ trong docstring** rằng HF không cung cấp — không được bịa số.

### 3.3 Không đổi

- `_require_pii_approval()` và toàn bộ hàng rào PII — giữ nguyên. Embed route cũng phải qua cổng đó vì nó gửi text ra ngoài.
- Không log prompt, response, credential — áp dụng y nguyên cho nhánh HF.
- `reopen_sampling.py` không sửa một dòng. Nó chỉ gọi `llm_client.embed()`.

## 4. Rủi ro PII mới — phải nêu rõ

Trước thay đổi này, mọi lệnh gọi ra ngoài đi tới **một** đích. Sau thay đổi có **hai** đích: `vllm.zalopay.vn` (nội bộ, text không rời mạng công ty) và `router.huggingface.co` (**bên thứ ba, ngoài công ty**).

Hệ quả: chữ ký duyệt PII ở spec gốc §4.2 bước 6 được ký với giả định một đích. **Phải xác nhận lại với PO** rằng đích HuggingFace cũng được duyệt, trước lần gọi embed đầu tiên. Text đã mask, nhưng đích đến là thông tin mới so với lúc ký.

Ghi vào artifact server-side: đích đến của từng loại request, để audit sau này biết dữ liệu đã đi đâu.

### 4.1 Trạng thái duyệt

**2026-07-30 — PO đã duyệt đích thứ hai `router.huggingface.co`.** PO tự xác nhận trong session ngày 2026-07-30, sau khi được nêu rõ: chữ ký ở spec gốc §4.2 bước 6 ký khi chỉ có một đích, và đích mới là bên thứ ba ngoài công ty. Phạm vi duyệt: text **đã mask** theo §4.2 spec gốc, gửi tới `router.huggingface.co` cho mục đích embedding phục vụ lấy mẫu phân tầng.

Cổng ở §6 bước 3 **đã mở**. Hai điểm dừng còn lại của spec gốc §10 (bước 8 `config/reopen_labels.v1.json`, bước 13 độ tự nhất quán người ≥ 85%) **không** bị ảnh hưởng — vẫn phải chờ.

Vẫn giữ nguyên: `cli.py` không expose cờ `pii_approved`, `eval-labels` hardcode `raise PIIApprovalRequiredError`. Chữ ký này duyệt **đích đến**, không phải duyệt gỡ hàng rào code.

## 5. Test

Không test nào gọi API thật.

| Test | Kiểm gì |
|---|---|
| `test_llm_client.py` (mở rộng) | `EMBED_PROVIDER` vắng → `EmbedSettings` sao chép `OPENAI_*`; giá trị lạ → `LLMConfigurationError`; `"hf"` thiếu biến → `LLMConfigurationError` |
| `test_llm_client.py` (mở rộng) | fake HF trả **2 chiều** → vector dùng trực tiếp, đúng số lượng và số chiều |
| `test_llm_client.py` (mở rộng) | fake HF trả **3 chiều** → mean-pool đúng, so với giá trị trung bình tính tay |
| `test_llm_client.py` (mở rộng) | vector lệch số chiều → `LLMServiceError`; số vector ≠ số input → raise |
| `test_llm_client.py` (mở rộng) | 130 input → đúng 3 request (64+64+2), thứ tự kết quả khớp thứ tự đầu vào |
| `test_llm_client.py` (mở rộng) | nhánh HF vẫn bị `_require_pii_approval()` chặn khi chưa duyệt |
| toàn bộ suite hiện có | **687 test phải xanh, không sửa test nào** — đây là bằng chứng tương thích ngược |

## 6. Thứ tự implement

1. `EmbedSettings` + `from_environment()` + test cấu hình. Chạy full suite, phải xanh.
2. Nhánh HF trong `embed()` + test cả hai dạng response + test batch. Chạy full suite.
3. **DỪNG — xác nhận PO duyệt đích HuggingFace (§4).**
4. Codex **không** tự chạy `sample-reopen` thật. Báo lại là đã sẵn sàng.

## 7. Ngoài phạm vi

- Chạy `sample-reopen` thật trên dữ liệu production — cần §6 bước 3 xong trước.
- Đổi bất kỳ ngưỡng, taxonomy, hay giai đoạn nào của spec gốc.
- Gỡ `OPENAI_EMBED_MODEL` khỏi danh sách bắt buộc — làm sau, khi không còn ai dùng route OpenAI.
- Tìm virtual key cho `litellm.zalopay.vn` — nếu sau này có, đặt `EMBED_PROVIDER="openai"` và trỏ `EMBED_BASE_URL` sang đó là xong, không sửa code lần nữa. Đó là lý do contract có `EMBED_PROVIDER` chứ không hardcode HF.
