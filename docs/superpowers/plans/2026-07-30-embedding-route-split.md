# Embedding Route Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tách đường embedding khỏi đường label để `llm_client.embed()` gọi được HuggingFace router, trong khi đường label vẫn đi `vllm.zalopay.vn`. Kết thúc: pipeline reopen sẵn sàng cho bước 7 của spec gốc §10.

**Architecture:** Sửa duy nhất `src/weekly_cs_report/llm_client.py` + test. `reopen_sampling.py` **không sửa một dòng** — nó chỉ gọi `llm_client.embed()`. `embed()` đã là `Protocol` (`llm_client.py:110`), thêm provider bằng nhánh mới trong implementation, không đổi caller.

**Tech Stack:** Python 3.9, `httpx`, `dataclasses`. Test: pytest + `httpx.MockTransport`. Không API thật, không thêm dependency.

**Spec nguồn:** `docs/superpowers/specs/2026-07-30-embedding-route-split-design.md`. Spec đó là phụ lục của `2026-07-30-reopen-reason-labeling-design.md` — không đổi taxonomy, ngưỡng, ba điểm dừng, ranh giới PII của spec gốc. Khi plan này và spec lệch nhau, mục "Spec sai / code thắng" dưới đây thắng.

---

## Global Constraints

- **Không API thật.** Không lệnh nào gọi ra `router.huggingface.co`, `vllm.zalopay.vn`, `api.openai.com`. Mọi test dùng `httpx.MockTransport`.
- **Không chạy `sample-reopen` hay `eval-labels` trên dữ liệu thật.** Ngoài phạm vi lượt này (spec §7).
- **Không gỡ hàng rào PII.** `_require_pii_approval()` (`llm_client.py:333`) giữ nguyên. `cli.py` **cố ý** không expose cờ `pii_approved`; `eval-labels` **cố ý** hardcode `raise PIIApprovalRequiredError`. Đó là hàng rào, không phải bug. Không "sửa".
- **Không log prompt, response, credential.** Áp y nguyên cho nhánh HF. `test_real_client_failure_has_no_secret_or_payload_in_the_error` (`tests/test_llm_client.py:170`) đang canh chuyện này — nó phải vẫn xanh.
- **Không `cat .env`, không in giá trị biến môi trường ra output.** Kiểm tên biến bằng `grep -o '^[A-Z_]*=' .env`.
- **Không `git init`, không chạy `git`.** Repo không có git. "Commit" thay bằng CHECKPOINT = chạy full suite.
- **Không tuyên bố đã verify Docker.**
- **Baseline: 687 test pass, exit 0.** **Không sửa test nào đang có.** Đây là bằng chứng tương thích ngược (spec §5 hàng cuối). Test cũ vỡ = dừng và báo, không sửa test cho xanh.
- Runtime deps chỉ 4: `fastapi`, `httpx`, `python-dotenv`, `uvicorn`. Không thêm dep.

## Chạy song song với việc 2

Session Codex khác đang làm `docs/superpowers/plans/2026-07-30-dashboard-ui-uplift.md` Lô 1, sửa `src/weekly_cs_report/static/index.html` và `tests/test_frontend_contract.py`. **Không giao file nào** với plan này.

Hệ quả bắt buộc:

- Chạy test scoped trước: `.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider`
- Khi chạy full suite, **thất bại trong `tests/test_frontend_contract.py` không phải của bạn** — session kia đang sửa file đó, trạng thái giữa đường là đỏ bình thường. Ghi nhận, đừng sửa, đừng chặn.
- Thất bại ở bất kỳ file nào **khác** `test_frontend_contract.py` là của bạn.
- Luôn thêm `-p no:cacheprovider` để hai session không tranh `.pytest_cache`.
- **Không sửa** `static/index.html`, `tests/test_frontend_contract.py`, `scripts/`, `docs/superpowers/reports/2026-07-30-ui-uplift-report.md`.

## Spec sai / code thắng — ba chỗ, đọc trước khi code

**S1 — `_post` không dùng lại được cho HF.** Spec §3.2 ghi "dùng cơ chế retry hiện có" như thể gọi `_post` là xong. Nhưng `_post` (`llm_client.py:337-359`) raise `LLMServiceError()` khi JSON decode ra thứ không phải `Mapping` (dòng 348-350). HF `pipeline/feature-extraction` trả **JSON array**, không phải object. Gọi `_post` cho HF là raise 100% số lần.
**Plan làm:** tách `_post` thành hai lớp. `_post_decoded(client, endpoint, payload) -> object` giữ nguyên vòng retry/backoff/timeout hiện có và trả về giá trị đã decode **chưa kiểm kiểu**. `_post` thành wrapper mỏng: gọi `_post_decoded` rồi enforce `Mapping` như cũ. Nhánh OpenAI đi qua `_post` → hành vi không đổi một bit. Nhánh HF gọi `_post_decoded` rồi tự kiểm là `list`.

**S2 — một `httpx.Client` không phục vụ được hai route.** `self._client` (`llm_client.py:277-284`) khoá cứng `base_url=settings.base_url` và header `Authorization: Bearer {settings.api_key}` — cả hai là của label route. Embed route ở host khác, key khác. `_is_relative_endpoint` (`:362`) chặn URL tuyệt đối và `follow_redirects=False`, nên không thể "gọi thẳng URL đầy đủ".
**Plan làm:** tạo `self._embed_client` thứ hai **chỉ khi** `provider == "hf"`, `base_url = EMBED_BASE_URL`, header `Authorization: Bearer {EMBED_API_KEY}`, cùng `timeout`/`verify`/`follow_redirects`/`transport`. Khi `provider == "openai"` thì `self._embed_client is self._client` (cùng object, không tạo mới). `close()` phải đóng cả hai và **không đóng hai lần cùng một object**.

**S3 — thêm field bắt buộc vào `LLMSettings` là vỡ test.** Spec §3.1 khai `embed: EmbedSettings` không default. Nhưng `tests/test_llm_client.py:19` có helper `_settings()` gọi `LLMSettings(...)` với 4 tham số; thêm field thứ 5 bắt buộc làm nó `TypeError`. Mà spec §5 hàng cuối đòi "687 test phải xanh, không sửa test nào".
**Plan làm:** `embed: EmbedSettings | None = None` (field cuối, có default). Thêm method `resolved_embed() -> EmbedSettings` trả `self.embed` nếu có, ngược lại dựng `EmbedSettings("openai", self.base_url, self.embed_model, self.api_key)`. `from_environment()` luôn điền `embed`. Client dùng `settings.resolved_embed()`, không đọc `settings.embed` trực tiếp.

## Contract biến môi trường

Đã có trong `.env` (mode `600`). Dùng đúng tên này, không tự đổi. **Không in giá trị.**

```dotenv
# Label route — 4 biến OPENAI_* giữ nguyên, vẫn bắt buộc
OPENAI_API_KEY=<chuỗi khác rỗng; vLLM tự host không kiểm key>
OPENAI_BASE_URL=<gateway nội bộ, /v1>
OPENAI_LABEL_MODEL=gemma-3-27b
OPENAI_EMBED_MODEL=unused-see-EMBED_MODEL

# Embed route
EMBED_PROVIDER=hf                 # "hf" | "openai"
EMBED_BASE_URL=<HF router, .../hf-inference/models>
EMBED_MODEL=intfloat/multilingual-e5-base
EMBED_API_KEY=<HF token scope Read>
```

`OPENAI_EMBED_MODEL` giữ trong danh sách bắt buộc để không phá kiểm tra "đủ 4 biến" hiện có. Giá trị `"unused-see-EMBED_MODEL"` là **cố ý**, để ai đọc log cũng biết ngay nó không được dùng khi `provider != "openai"`.

**`CLAUDE.md` repo dòng 67 đang stale**: nó ghi embed route trỏ `hiieu/halong_embedding`. Model đó `hf-inference` **không serve** (`"Model not supported by provider hf-inference"`, đo 2026-07-30). Model thật là `intfloat/multilingual-e5-base`, 768 chiều, `depth=2`. Sửa dòng đó ở Task 5.

## Quy ước prefix e5 — bỏ là hỏng im lặng

Dòng model e5 được train với tiền tố `"query: "` / `"passage: "`. Cho việc gom cụm, thêm `"query: "` vào **mọi** text một cách nhất quán trước khi gửi. Bỏ prefix làm chất lượng vector giảm mà **không có lỗi nào báo ra** — k-means vẫn chạy trên vector kém.

Áp dụng: chỉ khi `provider == "hf"` **và** `model` chứa `"e5"`. Model khác không có quy ước này; thêm bừa là làm bẩn input.

## File Structure

| File | Trách nhiệm | Thay đổi |
|---|---|---|
| `src/weekly_cs_report/llm_client.py` | Cấu hình + implementation client | `EmbedSettings`, `LLMSettings.embed`, `_post_decoded`, nhánh HF trong `embed()`, client thứ hai |
| `tests/test_llm_client.py` | Test cấu hình + hai nhánh embed | **Chỉ thêm** test, không sửa test cũ |
| `CLAUDE.md` (repo) | Trạng thái hiện tại | Sửa dòng 65-67 stale (Task 5) |

Không tạo module mới. Không sửa `reopen_sampling.py`, `content_labeler.py`, `reopen_eval.py`.

---

## Task 1: `EmbedSettings` và `from_environment()`

**Files:**
- Modify: `src/weekly_cs_report/llm_client.py:44-70`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class EmbedSettings:
      provider: str   # "hf" | "openai"
      base_url: str
      model: str
      api_key: str
  ```
  `LLMSettings` thêm field cuối `embed: EmbedSettings | None = None` và method `resolved_embed() -> EmbedSettings`. Hằng module `_EMBED_PROVIDERS = ("hf", "openai")`.
- Consumes: `os.environ` hoặc `Mapping[str, str]` truyền vào (chữ ký `from_environment` không đổi).

Luật cấu hình, đúng thứ tự kiểm:
1. Bốn biến `OPENAI_*` vẫn bắt buộc, thiếu → `LLMConfigurationError`. **Hành vi cũ không đổi.**
2. `EMBED_PROVIDER` vắng hoặc rỗng → mặc định `"openai"`, `EmbedSettings` sao chép y nguyên giá trị `OPENAI_*` (tương thích ngược).
3. `EMBED_PROVIDER` ngoài `{"hf","openai"}` → `LLMConfigurationError`. So khớp **phân biệt chữ hoa/thường** — `"HF"` phải raise. Cấu hình mơ hồ chết sớm tốt hơn đoán ý.
4. `EMBED_PROVIDER == "hf"` mà thiếu/rỗng bất kỳ trong `EMBED_BASE_URL`, `EMBED_MODEL`, `EMBED_API_KEY` → `LLMConfigurationError`.
5. `EMBED_PROVIDER == "openai"` với `EMBED_*` có mặt → dùng giá trị `EMBED_*` đó (cho phép trỏ sang `litellm.zalopay.vn` sau này không sửa code). Thiếu thì fallback `OPENAI_*`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_llm_client.py`, theo convention file đó (import từ `weekly_cs_report.llm_client`, dùng dict làm `environment`). Thêm `EmbedSettings` vào danh sách import.

```python
def test_embed_settings_default_to_the_openai_route_when_provider_is_absent():
    """Tương thích ngược: cấu hình cũ không có EMBED_* vẫn phải chạy y như trước."""
    settings = LLMSettings.from_environment(
        {
            "OPENAI_API_KEY": "key",
            "OPENAI_BASE_URL": "https://gateway.invalid/v1",
            "OPENAI_LABEL_MODEL": "label",
            "OPENAI_EMBED_MODEL": "embed",
        }
    )
    embed = settings.resolved_embed()
    assert embed.provider == "openai"
    assert embed.base_url == "https://gateway.invalid/v1"
    assert embed.model == "embed"
    assert embed.api_key == "key"


def test_embed_settings_read_the_hf_route_from_its_own_variables():
    settings = LLMSettings.from_environment(
        {
            "OPENAI_API_KEY": "key",
            "OPENAI_BASE_URL": "https://gateway.invalid/v1",
            "OPENAI_LABEL_MODEL": "label",
            "OPENAI_EMBED_MODEL": "unused-see-EMBED_MODEL",
            "EMBED_PROVIDER": "hf",
            "EMBED_BASE_URL": "https://router.invalid/models",
            "EMBED_MODEL": "intfloat/multilingual-e5-base",
            "EMBED_API_KEY": "hf-token",
        }
    )
    embed = settings.resolved_embed()
    assert (embed.provider, embed.base_url, embed.model, embed.api_key) == (
        "hf",
        "https://router.invalid/models",
        "intfloat/multilingual-e5-base",
        "hf-token",
    )
    assert settings.embed_model == "unused-see-EMBED_MODEL", "giữ để không phá kiểm tra 4 biến"


@pytest.mark.parametrize(
    "overrides",
    [
        {"EMBED_PROVIDER": "gemini"},
        {"EMBED_PROVIDER": "HF"},
        {"EMBED_PROVIDER": "hf"},
        {"EMBED_PROVIDER": "hf", "EMBED_BASE_URL": "https://router.invalid/models"},
        {
            "EMBED_PROVIDER": "hf",
            "EMBED_BASE_URL": "https://router.invalid/models",
            "EMBED_MODEL": "intfloat/multilingual-e5-base",
        },
        {
            "EMBED_PROVIDER": "hf",
            "EMBED_BASE_URL": "https://router.invalid/models",
            "EMBED_MODEL": "intfloat/multilingual-e5-base",
            "EMBED_API_KEY": "   ",
        },
    ],
)
def test_embed_settings_reject_unknown_provider_or_incomplete_hf_route(overrides):
    """Cấu hình nửa vời phải chết lúc đọc, không phải lúc gọi API."""
    with pytest.raises(LLMConfigurationError):
        LLMSettings.from_environment(
            {
                "OPENAI_API_KEY": "key",
                "OPENAI_BASE_URL": "https://gateway.invalid/v1",
                "OPENAI_LABEL_MODEL": "label",
                "OPENAI_EMBED_MODEL": "embed",
                **overrides,
            }
        )


def test_blank_embed_provider_falls_back_to_the_openai_route():
    settings = LLMSettings.from_environment(
        {
            "OPENAI_API_KEY": "key",
            "OPENAI_BASE_URL": "https://gateway.invalid/v1",
            "OPENAI_LABEL_MODEL": "label",
            "OPENAI_EMBED_MODEL": "embed",
            "EMBED_PROVIDER": "",
        }
    )
    assert settings.resolved_embed().provider == "openai"


def test_llm_settings_stays_constructible_with_four_positional_fields():
    """Test cũ dựng LLMSettings 4 tham số; field mới phải có default."""
    settings = LLMSettings("key", "https://gateway.invalid/v1", "label", "embed")
    assert settings.embed is None
    assert settings.resolved_embed().provider == "openai"
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider -k "embed_settings or four_positional or blank_embed_provider"
```
Kỳ vọng: FAIL — `EmbedSettings` và `resolved_embed` chưa tồn tại.

- [ ] **Step 3: Thêm `EmbedSettings` và sửa `LLMSettings`**

Chèn ngay **trước** `class LLMSettings` (dòng 44), và thay `LLMSettings` bằng:

```python
_EMBED_PROVIDERS = ("hf", "openai")


@dataclass(frozen=True)
class EmbedSettings:
    provider: str
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str
    label_model: str
    embed_model: str
    embed: EmbedSettings | None = None

    def resolved_embed(self) -> EmbedSettings:
        if self.embed is not None:
            return self.embed
        return EmbedSettings(
            provider="openai",
            base_url=self.base_url,
            model=self.embed_model,
            api_key=self.api_key,
        )

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> LLMSettings:
        values = os.environ if environment is None else environment
        required = (
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_LABEL_MODEL",
            "OPENAI_EMBED_MODEL",
        )
        configured = {key: values.get(key) for key in required}
        if any(not isinstance(value, str) or not value.strip() for value in configured.values()):
            raise LLMConfigurationError()
        api_key = configured["OPENAI_API_KEY"].strip()  # type: ignore[union-attr]
        base_url = configured["OPENAI_BASE_URL"].strip()  # type: ignore[union-attr]
        label_model = configured["OPENAI_LABEL_MODEL"].strip()  # type: ignore[union-attr]
        embed_model = configured["OPENAI_EMBED_MODEL"].strip()  # type: ignore[union-attr]
        return cls(
            api_key=api_key,
            base_url=base_url,
            label_model=label_model,
            embed_model=embed_model,
            embed=_embed_settings_from_environment(
                values,
                fallback=EmbedSettings(
                    provider="openai",
                    base_url=base_url,
                    model=embed_model,
                    api_key=api_key,
                ),
            ),
        )


def _embed_settings_from_environment(
    values: Mapping[str, str], *, fallback: EmbedSettings
) -> EmbedSettings:
    raw_provider = values.get("EMBED_PROVIDER")
    provider = raw_provider.strip() if isinstance(raw_provider, str) else ""
    if not provider:
        provider = "openai"
    if provider not in _EMBED_PROVIDERS:
        raise LLMConfigurationError()

    def value_of(key: str) -> str:
        raw = values.get(key)
        return raw.strip() if isinstance(raw, str) else ""

    base_url = value_of("EMBED_BASE_URL")
    model = value_of("EMBED_MODEL")
    api_key = value_of("EMBED_API_KEY")
    if provider == "hf":
        if not (base_url and model and api_key):
            raise LLMConfigurationError()
        return EmbedSettings(
            provider="hf", base_url=base_url, model=model, api_key=api_key
        )
    return EmbedSettings(
        provider="openai",
        base_url=base_url or fallback.base_url,
        model=model or fallback.model,
        api_key=api_key or fallback.api_key,
    )
```

`from __future__ import annotations` đã có ở đầu file, nên `EmbedSettings | None` chạy được trên Python 3.9.

- [ ] **Step 4: Chạy test scoped, phải PASS**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider
```
Kỳ vọng: xanh, kể cả `test_llm_settings_missing_required_values_fails_with_fixed_safe_code` (dòng 59) và helper `_settings()` (dòng 19).

- [ ] **Step 5: CHECKPOINT**

```bash
.venv/bin/pytest -q -p no:cacheprovider
```
Kỳ vọng: ≥692 pass. Thất bại trong `tests/test_frontend_contract.py` là của session kia — bỏ qua, ghi lại. Thất bại ở file khác là của bạn.

---

## Task 2: Tách `_post` thành hai lớp

**Files:**
- Modify: `src/weekly_cs_report/llm_client.py:337-359`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Produces: `_post_decoded(self, client: httpx.Client, endpoint: str, payload: Mapping[str, object]) -> object` — giữ nguyên vòng retry/backoff/timeout, trả giá trị đã decode **chưa kiểm kiểu**. `_post(self, endpoint, payload) -> Mapping[str, object]` thành wrapper enforce `Mapping`, gọi `_post_decoded(self._client, ...)`.
- Consumes: `self._max_attempts`, `self._backoff_base_s`, `self._sleep`.

Refactor thuần, **không đổi hành vi quan sát được**. Làm riêng một task để nếu nó phá gì thì thấy ngay, không lẫn với Task 4.

- [ ] **Step 1: Viết test canary**

```python
def test_post_wrapper_still_rejects_a_non_object_json_body():
    """_post_decoded nới kiểu; _post phải vẫn chặn body không phải object."""
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=[1, 2, 3])

    client = OpenAICompatibleLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint="/embeddings",
        pii_approved=True,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    with client:
        with pytest.raises(LLMServiceError):
            client.generate_structured(
                messages=[{"role": "user", "content": "x"}], response_schema={}
            )
    assert len(calls) == 1, "body sai kiểu không phải lỗi tạm thời, không được retry"
```

- [ ] **Step 2: Chạy để xác nhận trạng thái**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider -k post_wrapper
```
Kỳ vọng: **PASS ngay** — hành vi hiện tại đã đúng. Đây là canary; nó phải vẫn PASS sau Step 3. FAIL ngay ở bước này = giả định của plan sai, **dừng và báo**.

- [ ] **Step 3: Refactor**

Thay `_post` (dòng 337-359) bằng:

```python
    def _post(self, endpoint: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        decoded = self._post_decoded(self._client, endpoint, payload)
        if isinstance(decoded, Mapping):
            return dict(decoded)
        raise LLMServiceError()

    def _post_decoded(
        self,
        client: httpx.Client,
        endpoint: str,
        payload: Mapping[str, object],
    ) -> object:
        for attempt in range(self._max_attempts):
            try:
                response = client.post(endpoint, json=payload)
            except httpx.HTTPError:
                response = None
            if response is not None and response.is_success:
                try:
                    return response.json()
                except (TypeError, ValueError):
                    raise LLMServiceError() from None
            if attempt + 1 < self._max_attempts and (
                response is None
                or response.status_code == 429
                or 500 <= response.status_code < 600
            ):
                self._sleep(self._backoff_base_s * (2**attempt))
                continue
            raise LLMServiceError()
        raise AssertionError("unreachable")
```

Điều kiện retry giữ **nguyên văn**: `None` (lỗi mạng), `429`, `5xx`. HF trả `503` khi model đang load → đã nằm trong `5xx`, không cần luật riêng.

- [ ] **Step 4: Chạy test scoped**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider
```
Kỳ vọng: xanh, kể cả `test_real_structured_client_retries_boundedly_uses_timeout_and_reports_token_usage` (dòng 91) và `test_real_embedding_client_uses_configured_model_and_parses_usage` (dòng 140).

- [ ] **Step 5: CHECKPOINT**

```bash
.venv/bin/pytest -q -p no:cacheprovider
```
Kỳ vọng: ≥693 pass (trừ nhiễu `test_frontend_contract.py`).

---

## Task 3: Client thứ hai cho embed route

**Files:**
- Modify: `src/weekly_cs_report/llm_client.py:230-298`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Produces: `self._embed_settings: EmbedSettings`; `self._embed_client: httpx.Client`. `provider == "openai"` → `self._embed_client is self._client` (**cùng object**). `provider == "hf"` → client riêng, `base_url = EMBED_BASE_URL`, header `Authorization: Bearer {EMBED_API_KEY}`.
- `close()` đóng cả hai, **không đóng hai lần cùng một object**.
- Chữ ký `__init__` **không đổi** — `embedding_endpoint` vẫn bắt buộc, vẫn phải là đường dẫn tương đối.

Xem S2. `_is_relative_endpoint` và `follow_redirects=False` giữ nguyên — chúng là hàng rào SSRF, không phải trở ngại.

- [ ] **Step 1: Viết test thất bại**

```python
def _hf_settings(model: str = "intfloat/multilingual-e5-base") -> LLMSettings:
    return LLMSettings(
        "key",
        "https://gateway.invalid/v1",
        "label",
        "unused-see-EMBED_MODEL",
        EmbedSettings(
            provider="hf",
            base_url="https://router.invalid/models",
            model=model,
            api_key="hf-token",
        ),
    )


_HF_ENDPOINT = "/intfloat/multilingual-e5-base/pipeline/feature-extraction"


def test_hf_embed_route_uses_its_own_host_and_token_not_the_label_credentials():
    """Hai đích khác nhau: label đi gateway nội bộ, embed đi router bên thứ ba."""
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, json=[[0.1, 0.2], [0.3, 0.4]])

    client = OpenAICompatibleLLMClient(
        _hf_settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    with client:
        result = client.embed(["một", "hai"])

    assert len(seen) == 1
    url, authorization = seen[0]
    assert url.startswith("https://router.invalid/models/")
    assert "gateway.invalid" not in url
    assert authorization == "Bearer hf-token", "không được dùng key của label route"
    assert result.vectors == ((0.1, 0.2), (0.3, 0.4))


def test_openai_embed_route_reuses_the_single_client_and_closes_once():
    """provider openai không được tạo client thứ hai — đóng hai lần là bug."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.5]}]})

    client = OpenAICompatibleLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint="/embeddings",
        pii_approved=True,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    with client:
        assert client.embed(["x"]).vectors == ((0.5,),)
    client.close()  # gọi lần hai phải không nổ


def test_hf_embed_route_still_blocked_without_pii_approval():
    """Đích thứ ba cũng phải qua đúng cổng PII đó."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng khi chưa duyệt PII")

    client = OpenAICompatibleLLMClient(
        _hf_settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=False,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    with client:
        with pytest.raises(PIIApprovalRequiredError):
            client.embed(["x"])


def test_client_rejects_an_incomplete_embed_settings_at_construction():
    with pytest.raises(LLMConfigurationError):
        OpenAICompatibleLLMClient(
            LLMSettings(
                "key",
                "https://gateway.invalid/v1",
                "label",
                "embed",
                EmbedSettings("hf", "https://router.invalid/models", "model", "  "),
            ),
            structured_endpoint="/chat/completions",
            embedding_endpoint=_HF_ENDPOINT,
            pii_approved=True,
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[[0.1]])),
            sleep=lambda _seconds: None,
        )
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider -k "hf_embed_route or openai_embed_route or incomplete_embed_settings"
```
Kỳ vọng: FAIL — chưa có nhánh HF, request vẫn đi `gateway.invalid`.

- [ ] **Step 3: Validate `embed` trong `__init__`**

Trong khối validate ở đầu `__init__`, sau khối kiểm `settings` (dòng 245-254), thêm:

```python
        embed_settings = settings.resolved_embed()
        if embed_settings.provider not in _EMBED_PROVIDERS or not all(
            isinstance(value, str) and value.strip()
            for value in (
                embed_settings.base_url,
                embed_settings.model,
                embed_settings.api_key,
            )
        ):
            raise LLMConfigurationError()
```

- [ ] **Step 4: Tạo client thứ hai**

Sau khối tạo `self._client` (dòng 277-284), thêm:

```python
        self._embed_settings = embed_settings
        if embed_settings.provider == "hf":
            self._embed_client = httpx.Client(
                base_url=embed_settings.base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {embed_settings.api_key}"},
                timeout=httpx.Timeout(timeout_s),
                verify=True,
                follow_redirects=False,
                transport=transport,
            )
        else:
            self._embed_client = self._client
```

- [ ] **Step 5: Sửa `close()`**

Thay `close()` (dòng 286-287) bằng:

```python
    def close(self) -> None:
        if self._embed_client is not self._client:
            self._embed_client.close()
        self._client.close()
```

- [ ] **Step 6: Chạy test scoped**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider
```
Kỳ vọng: `test_hf_embed_route_uses_its_own_host...` **vẫn FAIL** (Task 4 mới parse array) — đó là RED có chủ đích. Ba test còn lại của Task 3 và toàn bộ test cũ phải PASS.

- [ ] **Step 7: CHECKPOINT**

```bash
.venv/bin/pytest -q -p no:cacheprovider
```
Ghi rõ test nào còn đỏ và vì sao.

---

## Task 4: Nhánh HF trong `embed()` — hai dạng response, batch 64, prefix e5

**Files:**
- Modify: `src/weekly_cs_report/llm_client.py:322-331` (`embed`), thêm helper cuối file
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Produces:
  - `_HF_MAX_BATCH = 64`
  - `_hf_prefixed(model, texts) -> list[str]` — thêm `"query: "` khi `"e5"` trong `model`, ngược lại trả nguyên.
  - `_hf_vectors(decoded, *, expected_count) -> tuple[tuple[float, ...], ...]` — **2 chiều** dùng trực tiếp, **3 chiều** mean-pool theo chiều token; kiểm cùng số chiều; kiểm số vector.
  - `embed()` rẽ nhánh theo `self._embed_settings.provider`. **Nhánh OpenAI không sửa một dòng.**
- Consumes: `_post_decoded` (Task 2), `self._embed_client` (Task 3).

Request HF:
```
POST {EMBED_BASE_URL}/{EMBED_MODEL}/pipeline/feature-extraction
Authorization: Bearer {EMBED_API_KEY}
{"inputs": ["query: text 1", "query: text 2"], "options": {"wait_for_model": true}}
```

**Đo thật 2026-07-30:** `multilingual-e5-base` trả `depth=2`, shape `[2, 768]` cho 2 input — đã pooling sẵn, đi nhánh trực tiếp. Bốn model khác trong bảng spec §1 cũng `depth=2`.

**Vẫn phải viết cả hai nhánh.** Đổi `EMBED_MODEL` sang model không cấu hình pooling thì response thành 3 chiều, và sai giả định ở đây cho ra **vector rác mà không báo lỗi nào** — k-means chạy bình thường trên rác. Đếm số chiều rồi rẽ nhánh, đừng hardcode.

`LLMUsage`: HF không trả token count. Đặt `input_tokens=0, output_tokens=0, total_tokens=0` và **ghi trong docstring** rằng HF không cung cấp. Không được bịa số.

- [ ] **Step 1: Viết test thất bại**

Cần `import json` ở đầu file test nếu chưa có.

```python
def _hf_client(handler, *, settings: LLMSettings | None = None) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        settings or _hf_settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


def test_hf_two_dimensional_response_is_used_directly():
    """multilingual-e5-base đã pooling sẵn: depth=2."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

    with _hf_client(handler) as client:
        result = client.embed(["một", "hai"])

    assert result.vectors == ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6))
    assert result.usage.total_tokens == 0, "HF không trả token count, không được bịa"
    assert bodies[0]["options"] == {"wait_for_model": True}
    assert bodies[0]["inputs"] == ["query: một", "query: hai"], "quy ước prefix dòng e5"


def test_hf_three_dimensional_response_is_mean_pooled_over_tokens():
    """Model không cấu hình pooling trả token-level; đọc sai cho ra vector rác im lặng."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                [[0.0, 1.0], [2.0, 3.0]],
                [[4.0, 6.0], [6.0, 10.0], [8.0, 14.0]],
            ],
        )

    with _hf_client(handler) as client:
        result = client.embed(["một", "hai"])

    assert result.vectors == ((1.0, 2.0), (6.0, 10.0))


@pytest.mark.parametrize(
    "body,count",
    [
        ([[0.1, 0.2], [0.3]], 2),
        ([[0.1, 0.2]], 2),
        ({"error": "boom"}, 1),
        ([[]], 1),
        ([[[0.1, 0.2], [0.3]]], 1),
    ],
)
def test_hf_rejects_malformed_response_shapes(body, count):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with _hf_client(handler) as client:
        with pytest.raises(LLMServiceError):
            client.embed([f"text {index}" for index in range(count)])


def test_hf_batches_at_sixty_four_and_preserves_input_order():
    """130 input -> 64 + 64 + 2, ghép theo đúng thứ tự đầu vào."""
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["inputs"]
        sizes.append(len(inputs))
        return httpx.Response(
            200, json=[[float(int(text.split()[-1]))] for text in inputs]
        )

    with _hf_client(handler) as client:
        result = client.embed([f"item {index}" for index in range(130)])

    assert sizes == [64, 64, 2]
    assert result.vectors == tuple((float(index),) for index in range(130))


def test_hf_rejects_a_dimension_change_between_batches():
    """Router đổi model giữa đường: lô 1 trả 2 chiều, lô 2 trả 1 chiều."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        inputs = json.loads(request.content)["inputs"]
        width = 2 if len(calls) == 1 else 1
        return httpx.Response(200, json=[[0.1] * width for _ in inputs])

    with _hf_client(handler) as client:
        with pytest.raises(LLMServiceError):
            client.embed([f"item {index}" for index in range(70)])


def test_hf_retries_a_503_while_the_model_loads():
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503, json={"error": "loading"})
        return httpx.Response(200, json=[[0.1]])

    with _hf_client(handler) as client:
        assert client.embed(["x"]).vectors == ((0.1,),)
    assert len(attempts) == 2


def test_non_e5_model_gets_no_prefix():
    """Prefix là quy ước của dòng e5; thêm bừa là làm bẩn input."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=[[0.1]])

    with _hf_client(handler, settings=_hf_settings("BAAI/bge-m3")) as client:
        client.embed(["một"])
    assert bodies[0]["inputs"] == ["một"]


def test_hf_refuses_an_empty_text_list():
    """Embed danh sách rỗng là lỗi gọi, không phải kết quả rỗng hợp lệ."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng cho danh sách rỗng")

    with _hf_client(handler) as client:
        with pytest.raises(LLMServiceError):
            client.embed([])
```

- [ ] **Step 2: Chạy để xác nhận RED**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider -k "hf_two_dimensional or hf_three_dimensional or hf_rejects or hf_batches or hf_retries or non_e5_model or hf_refuses"
```
Kỳ vọng: tất cả FAIL.

- [ ] **Step 3: Thêm helper cuối file**

Sau `_embedding_vectors` (dòng 372-391), thêm:

```python
_HF_MAX_BATCH = 64


def _hf_prefixed(model: str, texts: Sequence[str]) -> list[str]:
    if "e5" not in model:
        return list(texts)
    return [f"query: {text}" for text in texts]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _hf_single_vector(item: object) -> tuple[float, ...]:
    if not isinstance(item, list) or not item:
        raise LLMServiceError()
    if all(_is_number(value) for value in item):
        return tuple(float(value) for value in item)
    tokens: list[tuple[float, ...]] = []
    for token in item:
        if not isinstance(token, list) or not token:
            raise LLMServiceError()
        if not all(_is_number(value) for value in token):
            raise LLMServiceError()
        tokens.append(tuple(float(value) for value in token))
    widths = {len(token) for token in tokens}
    if len(widths) != 1:
        raise LLMServiceError()
    width = widths.pop()
    count = len(tokens)
    return tuple(
        sum(token[index] for token in tokens) / count for index in range(width)
    )


def _hf_vectors(
    decoded: object, *, expected_count: int
) -> tuple[tuple[float, ...], ...]:
    if not isinstance(decoded, list) or len(decoded) != expected_count:
        raise LLMServiceError()
    vectors = tuple(_hf_single_vector(item) for item in decoded)
    widths = {len(vector) for vector in vectors}
    if len(widths) != 1:
        raise LLMServiceError()
    return vectors
```

- [ ] **Step 4: Rẽ nhánh trong `embed()`**

Thay `embed` (dòng 322-331) bằng:

```python
    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed texts through the configured embed route.

        HuggingFace does not report token counts, so usage is reported as zeros
        for that provider rather than guessed.
        """
        self._require_pii_approval()
        if not all(isinstance(text, str) for text in texts):
            raise TypeError("texts must contain only strings")
        if self._embed_settings.provider == "hf":
            return self._embed_via_hf(texts)
        payload = self._post(
            self._embedding_endpoint,
            {"model": self._settings.embed_model, "input": list(texts)},
        )
        vectors = _embedding_vectors(payload, expected_count=len(texts))
        return EmbeddingResult(vectors=vectors, usage=_usage_from_payload(payload))

    def _embed_via_hf(self, texts: Sequence[str]) -> EmbeddingResult:
        ordered = list(texts)
        if not ordered:
            raise LLMServiceError()
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(ordered), _HF_MAX_BATCH):
            batch = ordered[start : start + _HF_MAX_BATCH]
            decoded = self._post_decoded(
                self._embed_client,
                self._embedding_endpoint,
                {
                    "inputs": _hf_prefixed(self._embed_settings.model, batch),
                    "options": {"wait_for_model": True},
                },
            )
            vectors.extend(_hf_vectors(decoded, expected_count=len(batch)))
        if len(vectors) != len(ordered) or len({len(v) for v in vectors}) != 1:
            raise LLMServiceError()
        return EmbeddingResult(
            vectors=tuple(vectors),
            usage=LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0),
        )
```

Kiểm số chiều **hai lần** là cố ý: `_hf_vectors` kiểm trong một lô, `_embed_via_hf` kiểm xuyên các lô. Lô 1 trả 768 chiều và lô 2 trả 384 chiều là kịch bản thật khi router đổi model giữa đường — `test_hf_rejects_a_dimension_change_between_batches` canh chuyện đó.

- [ ] **Step 5: Chạy test scoped**

```bash
.venv/bin/pytest -q tests/test_llm_client.py -p no:cacheprovider
```
Kỳ vọng: **toàn bộ xanh**, kể cả `test_hf_embed_route_uses_its_own_host...` từ Task 3 và bốn test cũ.

- [ ] **Step 6: CHECKPOINT**

```bash
.venv/bin/pytest -q -p no:cacheprovider
```
Kỳ vọng: ≥703 pass (trừ nhiễu `test_frontend_contract.py`).

---

## Task 5: Nối dây cấu hình và sửa doc stale

**Files:**
- Modify: chỗ dựng `OpenAICompatibleLLMClient` (tìm bằng grep)
- Modify: `CLAUDE.md` (repo) dòng 65-67

**Interfaces:**
- Consumes: `LLMSettings.from_environment()`, `EmbedSettings.provider`.
- Produces: `embedding_endpoint` đúng theo provider. `"hf"` → `/{EMBED_MODEL}/pipeline/feature-extraction`. `"openai"` → `/embeddings` như cũ.

- [ ] **Step 1: Tìm chỗ dựng client**

```bash
grep -rn "OpenAICompatibleLLMClient(" src/weekly_cs_report/ | grep -v "^src/weekly_cs_report/llm_client.py:227"
grep -rn "embedding_endpoint" src/weekly_cs_report/ tests/
```

Nếu **không** chỗ nào ngoài `llm_client.py` dựng client (tức việc nối dây chưa tồn tại): **dừng và báo**. Đừng tự phát minh chỗ nối dây — đó là quyết định kiến trúc, không phải việc của lượt này.

- [ ] **Step 2: Viết test thất bại cho chỗ nối dây**

Test khẳng định: với `EMBED_PROVIDER=hf`, `embedding_endpoint` được dựng là `/{model}/pipeline/feature-extraction`; với `openai`, vẫn `/embeddings`. Viết theo convention của file test đang phủ hàm đó (grep Step 1 chỉ ra file nào). **Không sửa test cũ trong file đó.**

- [ ] **Step 3: RED, implement, xanh**

```bash
.venv/bin/pytest -q <file test tương ứng> -p no:cacheprovider
```

- [ ] **Step 4: Sửa `CLAUDE.md`**

Dòng 67, từ:
```
- `.env` hiện trỏ label route sang `vllm.zalopay.vn/v1` + `gemma-3-27b` (keyless, đã test `200`); embed route sang HF router + `hiieu/halong_embedding`. Biến `EMBED_*` **chưa có code đọc** — là contract chờ implement.
```
Thành:
```
- `.env` hiện trỏ label route sang `vllm.zalopay.vn/v1` + `gemma-3-27b` (keyless, đã test `200`); embed route sang HF router + `intfloat/multilingual-e5-base` (768 chiều, `depth=2`). `hiieu/halong_embedding` **không dùng được** — `hf-inference` trả `"Model not supported by provider hf-inference"`. Biến `EMBED_*` đã có code đọc từ 2026-07-30 (`EmbedSettings` trong `llm_client.py`).
```

Dòng 65 hiện nói "Chờ label route + embed route chạy được, rồi `config/reopen_labels.v1.json`". Sửa thành: cổng PII bước 6 đã được PO duyệt 2026-07-30 kể cả đích HuggingFace (xem spec `2026-07-30-embedding-route-split-design.md` §4.1); embed route đã chạy; còn chờ bước 8 (`config/reopen_labels.v1.json` hiện `"labels": []`).

- [ ] **Step 5: CHECKPOINT CUỐI**

```bash
.venv/bin/pytest -q -p no:cacheprovider
```
Kỳ vọng: ≥704 pass, exit 0 — **trừ** nhiễu từ `test_frontend_contract.py` nếu session việc 2 còn chạy. Chờ session kia xong rồi chạy lại full suite để có số sạch.

- [ ] **Step 6: DỪNG**

**Không chạy `sample-reopen` thật.** Báo lại là đã sẵn sàng. Cổng PII ở spec §6 bước 3 đã được PO duyệt ngày 2026-07-30 (spec §4.1), nhưng bước 8 của spec gốc §10 (`config/reopen_labels.v1.json` hiện `"labels": []`) vẫn chưa xong — chạy `sample-reopen` lúc này là chạy vào một điểm dừng khác.

---

## Nghiệm thu

| Tiêu chí | Cách kiểm | Ngưỡng |
|---|---|---|
| Tương thích ngược | `.venv/bin/pytest -q -p no:cacheprovider` | Không test cũ nào bị sửa; tất cả xanh |
| Cấu hình fail sớm | test Task 1 | `EMBED_PROVIDER` lạ / `"HF"` / `hf` thiếu biến → `LLMConfigurationError` |
| Hai đích tách thật | test Task 3 | request embed đi `router.invalid`, header là token HF, không phải key label |
| Hai dạng response | test Task 4 | 2 chiều dùng trực tiếp; 3 chiều mean-pool đúng giá trị tính tay |
| Batch và thứ tự | test Task 4 | 130 input → `[64, 64, 2]`, thứ tự khớp đầu vào |
| Đổi số chiều giữa lô | test Task 4 | raise `LLMServiceError`, không ghép rác |
| Không bịa usage | test Task 4 | `usage.total_tokens == 0` cho nhánh HF |
| Hàng rào PII | test Task 3 | nhánh HF vẫn raise `PIIApprovalRequiredError` khi chưa duyệt |
| Không rò credential | `test_real_client_failure_has_no_secret_or_payload_in_the_error` | vẫn xanh |
| Không gọi mạng thật | đọc lại diff test | mọi test dùng `httpx.MockTransport` |

## Ngoài phạm vi

- Chạy `sample-reopen` / `eval-labels` thật trên dữ liệu production.
- Đổi bất kỳ ngưỡng, taxonomy, hay giai đoạn nào của spec gốc `2026-07-30-reopen-reason-labeling-design.md`.
- Gỡ `OPENAI_EMBED_MODEL` khỏi danh sách bắt buộc — làm sau, khi không còn ai dùng route OpenAI.
- Tìm virtual key cho `litellm.zalopay.vn`. Có rồi thì đặt `EMBED_PROVIDER="openai"` + `EMBED_BASE_URL` trỏ sang đó là xong, **không sửa code lần nữa**. Đó là lý do contract có `EMBED_PROVIDER` chứ không hardcode HF.
- Ghi đích đến của từng request vào artifact server-side để audit (spec §4 câu cuối). Việc riêng, cần quyết định artifact nào và mode file.
- Prefix `"passage: "` cho dòng e5. Chỉ cần khi làm retrieval bất đối xứng; việc này là gom cụm nên `"query: "` nhất quán là đủ.
