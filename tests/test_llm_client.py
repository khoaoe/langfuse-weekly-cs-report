from __future__ import annotations

from collections.abc import Sequence
import json

import httpx
import pytest

from weekly_cs_report.llm_client import (
    EmbedSettings,
    FakeLLMClient,
    GemmaHFLLMClient,
    LabelSettings,
    LLMClient,
    LLMConfigurationError,
    LLMSettings,
    LLMServiceError,
    PIIApprovalRequiredError,
)


def _settings(
    embed_model: str = "intfloat/multilingual-e5-base",
    *,
    label_base_url: str = "https://gemma-gateway.invalid/v1",
    embed_base_url: str = "https://hf-router.invalid/hf-inference/models",
) -> LLMSettings:
    return LLMSettings(
        label=LabelSettings(
            base_url=label_base_url,
            model="gemma-3-27b",
            api_key="test-secret-that-must-not-appear-in-errors",
        ),
        embed=EmbedSettings(
            base_url=embed_base_url,
            model=embed_model,
            api_key="hf-token",
        ),
    )


_HF_ENDPOINT = "/intfloat/multilingual-e5-base/pipeline/feature-extraction"
_ENVIRONMENT = {
    "LABEL_API_KEY": "gemma-key",
    "LABEL_BASE_URL": "https://gemma-gateway.invalid/v1",
    "LABEL_MODEL": "gemma-3-27b",
    "EMBED_BASE_URL": "https://hf-router.invalid/hf-inference/models",
    "EMBED_MODEL": "intfloat/multilingual-e5-base",
    "EMBED_API_KEY": "hf-token",
}


class _MappingSequence(dict, Sequence):
    pass


def _transport_args(handler):
    return {
        "label_transport": httpx.MockTransport(handler),
        "embed_transport": httpx.MockTransport(handler),
    }


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
    "texts",
    (
        "abc",
        b"abc",
        bytearray(b"abc"),
        {"text": "actual"},
        _MappingSequence({"text": "actual"}),
        iter(("abc",)),
        ["abc", 1],
    ),
)
def test_fake_embed_rejects_invalid_top_level_text_containers(texts):
    with pytest.raises(TypeError):
        FakeLLMClient().embed(texts)


@pytest.mark.parametrize("missing_key", tuple(_ENVIRONMENT))
def test_llm_settings_missing_required_values_fails_with_fixed_safe_code(missing_key):
    environment = {key: value for key, value in _ENVIRONMENT.items() if key != missing_key}

    with pytest.raises(LLMConfigurationError) as raised:
        LLMSettings.from_environment(environment)

    assert raised.value.code == "llm_configuration_unavailable"
    assert str(raised.value) == "llm configuration unavailable"
    assert _ENVIRONMENT[missing_key] not in str(raised.value)


@pytest.mark.parametrize("blank_key", tuple(_ENVIRONMENT))
def test_llm_settings_rejects_blank_active_values(blank_key):
    environment = {**_ENVIRONMENT, blank_key: " \t "}

    with pytest.raises(LLMConfigurationError):
        LLMSettings.from_environment(environment)


def test_llm_settings_reads_only_the_required_gemma_and_hf_routes():
    settings = LLMSettings.from_environment(
        {key: f"  {value}  " for key, value in _ENVIRONMENT.items()}
    )

    assert settings == LLMSettings(
        label=LabelSettings(
            base_url="https://gemma-gateway.invalid/v1",
            model="gemma-3-27b",
            api_key="gemma-key",
        ),
        embed=EmbedSettings(
            base_url="https://hf-router.invalid/hf-inference/models",
            model="intfloat/multilingual-e5-base",
            api_key="hf-token",
        ),
    )


@pytest.mark.parametrize("base_url_key", ("LABEL_BASE_URL", "EMBED_BASE_URL"))
@pytest.mark.parametrize(
    "unsafe_base_url",
    (
        "http://plaintext.invalid/v1",
        "ftp://files.invalid/models",
        "/relative/path",
        "https:///missing-host",
        "https://user:password@gateway.invalid/v1",
        "https://gateway.invalid/v1?debug=true",
        "https://gateway.invalid/v1#fragment",
    ),
)
def test_environment_rejects_unsafe_label_and_embed_base_urls(
    base_url_key, unsafe_base_url
):
    with pytest.raises(LLMConfigurationError):
        LLMSettings.from_environment(
            {**_ENVIRONMENT, base_url_key: unsafe_base_url}
        )


@pytest.mark.parametrize(
    ("label_base_url", "embed_base_url"),
    (
        (
            "http://gemma-gateway.invalid/v1",
            "https://hf-router.invalid/hf-inference/models",
        ),
        (
            "https://gemma-gateway.invalid/v1",
            "https://user@hf-router.invalid/hf-inference/models",
        ),
    ),
)
def test_direct_client_rejects_unsafe_label_and_embed_base_urls(
    label_base_url, embed_base_url
):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid configuration must fail before HTTP")

    with pytest.raises(LLMConfigurationError):
        GemmaHFLLMClient(
            _settings(
                label_base_url=label_base_url,
                embed_base_url=embed_base_url,
            ),
            structured_endpoint="/chat/completions",
            embedding_endpoint=_HF_ENDPOINT,
            pii_approved=True,
            **_transport_args(handler),
        )


@pytest.mark.parametrize(
    "unsafe_model",
    (
        "",
        "/intfloat/multilingual-e5-base",
        "intfloat/multilingual-e5-base/",
        "intfloat//multilingual-e5-base",
        "intfloat/./multilingual-e5-base",
        "intfloat/../multilingual-e5-base",
        r"intfloat\multilingual-e5-base",
        "intfloat/multilingual-e5-base?revision=main",
        "intfloat/multilingual-e5-base#fragment",
        "intfloat/%2e%2e/multilingual-e5-base",
        "intfloat/%2Fmultilingual-e5-base",
        "organization/model/extra-path",
    ),
)
def test_environment_rejects_unsafe_hf_repo_ids(unsafe_model):
    with pytest.raises(LLMConfigurationError):
        LLMSettings.from_environment(
            {**_ENVIRONMENT, "EMBED_MODEL": unsafe_model}
        )


@pytest.mark.parametrize(
    "unsafe_model",
    (
        "../multilingual-e5-base",
        "intfloat/%2e%2e/secret",
        r"intfloat\multilingual-e5-base",
    ),
)
def test_direct_client_rejects_unsafe_hf_repo_ids(unsafe_model):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid configuration must fail before HTTP")

    with pytest.raises(LLMConfigurationError):
        GemmaHFLLMClient(
            _settings(unsafe_model),
            structured_endpoint="/chat/completions",
            embedding_endpoint=_HF_ENDPOINT,
            pii_approved=True,
            **_transport_args(handler),
        )


def test_post_wrapper_still_rejects_a_non_object_json_body():
    """_post_decoded nới kiểu; _post phải vẫn chặn body không phải object."""
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=[1, 2, 3])

    client = GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        **_transport_args(handler),
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

    client = GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        **_transport_args(handler),
        sleep=lambda _seconds: None,
    )
    with client:
        result = client.embed(["một", "hai"])

    assert len(seen) == 1
    url, authorization = seen[0]
    assert url.startswith("https://hf-router.invalid/hf-inference/models/")
    assert "gemma-gateway.invalid" not in url
    assert authorization == "Bearer hf-token", "không được dùng key của label route"
    assert result.vectors == ((0.1, 0.2), (0.3, 0.4))


def test_label_and_embed_clients_are_distinct_and_close_is_idempotent():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[0.5]])

    client = GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        **_transport_args(handler),
        sleep=lambda _seconds: None,
    )

    assert client._label_client is not client._embed_client
    client.close()
    client.close()


def test_client_rejects_a_shared_non_default_transport():
    shared_transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={})
    )

    with pytest.raises(ValueError) as raised:
        GemmaHFLLMClient(
            _settings(),
            structured_endpoint="/chat/completions",
            embedding_endpoint=_HF_ENDPOINT,
            pii_approved=True,
            label_transport=shared_transport,
            embed_transport=shared_transport,
        )

    assert str(raised.value) == "label and embed transports must be distinct"


@pytest.mark.parametrize("pii_approved", (True, False))
def test_calls_after_close_fail_with_the_safe_service_error_without_http(
    pii_approved
):
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={})

    client = GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=pii_approved,
        **_transport_args(handler),
    )
    client.close()

    with pytest.raises(LLMServiceError) as structured_error:
        client.generate_structured(
            messages=({"role": "user", "content": "đã mask"},),
            response_schema={"type": "object"},
        )
    with pytest.raises(LLMServiceError) as embed_error:
        client.embed(("đã mask",))

    assert str(structured_error.value) == "llm api unavailable"
    assert str(embed_error.value) == "llm api unavailable"
    assert calls == []


def test_hf_embed_route_still_blocked_without_pii_approval():
    """Đích thứ ba cũng phải qua đúng cổng PII đó."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("không được gọi mạng khi chưa duyệt PII")

    client = GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=False,
        **_transport_args(handler),
        sleep=lambda _seconds: None,
    )
    with client:
        with pytest.raises(PIIApprovalRequiredError):
            client.embed(["x"])


@pytest.mark.parametrize(
    "texts",
    (
        "abc",
        b"abc",
        bytearray(b"abc"),
        {"text": "actual"},
        _MappingSequence({"text": "actual"}),
        iter(("abc",)),
        ["abc", 1],
    ),
)
def test_hf_embed_rejects_invalid_top_level_text_containers_without_http(texts):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid input must fail before HTTP")

    with GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        **_transport_args(handler),
    ) as client:
        with pytest.raises(TypeError):
            client.embed(texts)


def test_client_rejects_an_incomplete_embed_settings_at_construction():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[0.1]])

    with pytest.raises(LLMConfigurationError):
        GemmaHFLLMClient(
            LLMSettings(
                label=LabelSettings(
                    base_url="https://gemma-gateway.invalid/v1",
                    model="gemma-3-27b",
                    api_key="label-key",
                ),
                embed=EmbedSettings(
                    base_url="https://hf-router.invalid/hf-inference/models",
                    model="intfloat/multilingual-e5-base",
                    api_key="  ",
                ),
            ),
            structured_endpoint="/chat/completions",
            embedding_endpoint=_HF_ENDPOINT,
            pii_approved=True,
            **_transport_args(handler),
            sleep=lambda _seconds: None,
        )


@pytest.mark.parametrize(
    ("structured_endpoint", "embedding_endpoint"),
    [
        ("https://unexpected.invalid/chat", _HF_ENDPOINT),
        ("/chat/completions", "https://unexpected.invalid/embed"),
        ("/../chat/completions", _HF_ENDPOINT),
        ("/chat/completions", "/model/%2e%2e/embed"),
    ],
)
def test_client_rejects_non_relative_endpoints(
    structured_endpoint, embedding_endpoint
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(LLMConfigurationError):
        GemmaHFLLMClient(
            _settings(),
            structured_endpoint=structured_endpoint,
            embedding_endpoint=embedding_endpoint,
            pii_approved=True,
            **_transport_args(handler),
        )


def test_factory_wires_gemma_and_hf_routes_with_separate_credentials():
    seen: list[tuple[str, str | None, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((str(request.url), request.headers.get("authorization"), body))
        if request.url.host == "gemma-gateway.invalid":
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"label": "other"})}}
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                },
            )
        return httpx.Response(200, json=[[0.1, 0.2]])

    with GemmaHFLLMClient.from_environment(
        _ENVIRONMENT,
        pii_approved=True,
        **_transport_args(handler),
        sleep=lambda _seconds: None,
    ) as client:
        generated = client.generate_structured(
            messages=({"role": "user", "content": "đã mask"},),
            response_schema={"type": "object"},
        )
        embedded = client.embed(("đã mask",))

    assert generated.value == {"label": "other"}
    assert embedded.vectors == ((0.1, 0.2),)
    assert len(seen) == 2
    label_url, label_authorization, label_body = seen[0]
    embed_url, embed_authorization, embed_body = seen[1]
    assert label_url == "https://gemma-gateway.invalid/v1/chat/completions"
    assert label_authorization == "Bearer gemma-key"
    assert label_body["model"] == "gemma-3-27b"
    assert embed_url == (
        "https://hf-router.invalid/hf-inference/models/"
        "intfloat/multilingual-e5-base/pipeline/feature-extraction"
    )
    assert embed_authorization == "Bearer hf-token"
    assert embed_body == {
        "inputs": ["query: đã mask"],
        "options": {"wait_for_model": True},
    }


def _hf_client(handler, *, settings: LLMSettings | None = None) -> GemmaHFLLMClient:
    return GemmaHFLLMClient(
        settings or _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        **_transport_args(handler),
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


@pytest.mark.parametrize(
    "non_finite_literal",
    ("NaN", "Infinity", "-Infinity"),
    ids=("nan", "positive-infinity", "negative-infinity"),
)
@pytest.mark.parametrize(
    "token_level",
    (False, True),
    ids=("direct-vector", "token-level-vector"),
)
def test_hf_rejects_non_finite_direct_and_token_vector_values(
    non_finite_literal, token_level
):
    body = (
        f"[[[{non_finite_literal}, 0.2], [0.3, 0.4]]]"
        if token_level
        else f"[[{non_finite_literal}, 0.2]]"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode("ascii"),
            headers={"Content-Type": "application/json"},
        )

    with _hf_client(handler) as client:
        with pytest.raises(LLMServiceError):
            client.embed(["text"])


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

    with _hf_client(handler, settings=_settings("BAAI/bge-m3")) as client:
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

    with GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/structured",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=False,
        **_transport_args(handler),
    ) as client:
        with pytest.raises(PIIApprovalRequiredError) as raised:
            client.embed(("đã mask",))

    assert raised.value.code == "pii_approval_required"
    assert str(raised.value) == "pii approval required"
    assert calls == 0


def test_structured_request_serializes_mapping_content_without_mutating_messages():
    seen_payloads: list[dict] = []
    mapping_content = {
        "z": "đã mask",
        "a": {"second": 2, "first": "một"},
    }
    messages = [
        {"role": "system", "content": "giữ nguyên"},
        {"role": "user", "content": mapping_content, "name": "masked-user"},
    ]

    def label_handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"label": "other"})}}
                ]
            },
        )

    def embed_handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("structured generation must not use the embed route")

    with GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/chat/completions",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        label_transport=httpx.MockTransport(label_handler),
        embed_transport=httpx.MockTransport(embed_handler),
    ) as client:
        client.generate_structured(
            messages=messages,
            response_schema={"type": "object"},
        )

    assert seen_payloads[0]["messages"] == [
        {"role": "system", "content": "giữ nguyên"},
        {
            "role": "user",
            "content": '{"a":{"first":"một","second":2},"z":"đã mask"}',
            "name": "masked-user",
        },
    ]
    assert messages[0]["content"] == "giữ nguyên"
    assert messages[1]["content"] is mapping_content
    assert mapping_content == {
        "z": "đã mask",
        "a": {"second": 2, "first": "một"},
    }


def test_real_structured_client_retries_boundedly_uses_timeout_and_reports_token_usage():
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.url.path == "/v1/structured"
        assert request.extensions["timeout"]["connect"] == 2.5
        assert request.headers["authorization"] == "Bearer test-secret-that-must-not-appear-in-errors"
        assert json.loads(request.content) == {
            "model": "gemma-3-27b",
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

    with GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/structured",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        timeout_s=2.5,
        max_attempts=2,
        backoff_base_s=0.25,
        sleep=sleeps.append,
        **_transport_args(handler),
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


def test_real_client_failure_has_no_secret_or_payload_in_the_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="response text must never be exposed")

    with GemmaHFLLMClient(
        _settings(),
        structured_endpoint="/structured",
        embedding_endpoint=_HF_ENDPOINT,
        pii_approved=True,
        max_attempts=1,
        **_transport_args(handler),
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
