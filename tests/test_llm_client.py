from __future__ import annotations

import json

import httpx
import pytest

from weekly_cs_report.llm_client import (
    EmbedSettings,
    FakeLLMClient,
    LLMClient,
    LLMConfigurationError,
    LLMSettings,
    LLMServiceError,
    OpenAICompatibleLLMClient,
    PIIApprovalRequiredError,
)


def _settings() -> LLMSettings:
    return LLMSettings(
        api_key="test-secret-that-must-not-appear-in-errors",
        base_url="https://gateway.example.internal",
        label_model="approved-label-model",
        embed_model="approved-embed-model",
    )


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


def test_fake_client_is_deterministic_and_never_uses_a_network_transport():
    fake = FakeLLMClient(structured_outputs=({"label": "other"},), embedding_dimensions=4)

    generated = fake.generate_structured(
        messages=({"role": "user", "content": "đã mask"},),
        response_schema={"type": "object"},
    )
    first_embeddings = fake.embed(("khách quay lại", "đã mask"))
    second_embeddings = fake.embed(("khách quay lại", "đã mask"))

    assert generated.value == {"label": "other"}
    assert isinstance(fake, LLMClient)
    assert generated.usage.input_tokens > 0
    assert generated.usage.output_tokens > 0
    assert first_embeddings.vectors == second_embeddings.vectors
    assert len(first_embeddings.vectors) == 2
    assert all(len(vector) == 4 for vector in first_embeddings.vectors)
    assert first_embeddings.usage.input_tokens > 0


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "OPENAI_API_KEY": "secret",
            "OPENAI_BASE_URL": "https://gateway.example.internal",
            "OPENAI_LABEL_MODEL": "label",
        },
    ],
)
def test_llm_settings_missing_required_values_fails_with_fixed_safe_code(environment):
    with pytest.raises(LLMConfigurationError) as raised:
        LLMSettings.from_environment(environment)

    assert raised.value.code == "llm_configuration_unavailable"
    assert str(raised.value) == "llm configuration unavailable"
    assert "secret" not in str(raised.value)


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
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=[[0.1]])
            ),
            sleep=lambda _seconds: None,
        )


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


def test_real_client_cannot_call_network_without_explicit_pii_approval():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": []})

    with OpenAICompatibleLLMClient(
        _settings(),
        structured_endpoint="/structured",
        embedding_endpoint="/embeddings",
        pii_approved=False,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(PIIApprovalRequiredError) as raised:
            client.embed(("đã mask",))

    assert raised.value.code == "pii_approval_required"
    assert str(raised.value) == "pii approval required"
    assert calls == 0


def test_real_structured_client_retries_boundedly_uses_timeout_and_reports_token_usage():
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.url.path == "/structured"
        assert request.extensions["timeout"]["connect"] == 2.5
        assert request.headers["authorization"] == "Bearer test-secret-that-must-not-appear-in-errors"
        assert json.loads(request.content) == {
            "model": "approved-label-model",
            "messages": [{"role": "user", "content": "đã mask"}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "label"}},
        }
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"label": "other"})}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            },
        )

    with OpenAICompatibleLLMClient(
        _settings(),
        structured_endpoint="/structured",
        embedding_endpoint="/embeddings",
        pii_approved=True,
        timeout_s=2.5,
        max_attempts=2,
        backoff_base_s=0.25,
        sleep=sleeps.append,
        transport=httpx.MockTransport(handler),
    ) as client:
        generated = client.generate_structured(
            messages=({"role": "user", "content": "đã mask"},),
            response_schema={"type": "json_schema", "json_schema": {"name": "label"}},
        )

    assert attempts == 2
    assert sleeps == [0.25]
    assert generated.value == {"label": "other"}
    assert generated.usage.input_tokens == 7
    assert generated.usage.output_tokens == 3
    assert generated.usage.total_tokens == 10


def test_real_embedding_client_uses_configured_model_and_parses_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embeddings"
        assert json.loads(request.content) == {
            "model": "approved-embed-model",
            "input": ["masked one", "masked two"],
        }
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}],
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            },
        )

    with OpenAICompatibleLLMClient(
        _settings(),
        structured_endpoint="/structured",
        embedding_endpoint="/embeddings",
        pii_approved=True,
        transport=httpx.MockTransport(handler),
    ) as client:
        embeddings = client.embed(("masked one", "masked two"))

    assert embeddings.vectors == ((0.1, 0.2), (0.3, 0.4))
    assert embeddings.usage.input_tokens == 5
    assert embeddings.usage.output_tokens == 0
    assert embeddings.usage.total_tokens == 5


def test_real_client_failure_has_no_secret_or_payload_in_the_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="response text must never be exposed")

    with OpenAICompatibleLLMClient(
        _settings(),
        structured_endpoint="/structured",
        embedding_endpoint="/embeddings",
        pii_approved=True,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(LLMServiceError) as raised:
            client.generate_structured(
                messages=({"role": "user", "content": "sensitive prompt text"},),
                response_schema={"type": "object"},
            )

    assert raised.value.code == "llm_api_unavailable"
    assert str(raised.value) == "llm api unavailable"
    assert "secret" not in str(raised.value)
    assert "sensitive" not in str(raised.value)
    assert "response text" not in str(raised.value)
