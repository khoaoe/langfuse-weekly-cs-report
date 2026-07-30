from __future__ import annotations

"""PII-gated, no-logging client boundary for reopen-labeling models.

The production client intentionally has no default model or endpoint.  A
caller must provide gateway-approved values and explicitly approve the PII
route before any request can leave this process.  Prompt, response, and
credential values are never logged or included in raised errors.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import os
import time
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

import httpx


class LLMConfigurationError(RuntimeError):
    code = "llm_configuration_unavailable"

    def __init__(self) -> None:
        super().__init__("llm configuration unavailable")


class PIIApprovalRequiredError(RuntimeError):
    code = "pii_approval_required"

    def __init__(self) -> None:
        super().__init__("pii approval required")


class LLMServiceError(RuntimeError):
    code = "llm_api_unavailable"

    def __init__(self) -> None:
        super().__init__("llm api unavailable")


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


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class StructuredGeneration:
    value: Mapping[str, object]
    usage: LLMUsage


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: tuple[tuple[float, ...], ...]
    usage: LLMUsage


StructuredRequestBuilder = Callable[
    [str, Sequence[Mapping[str, object]], Mapping[str, object]], Mapping[str, object]
]
StructuredResponseParser = Callable[[Mapping[str, object]], Mapping[str, object]]


@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface shared by fake and PII-gated real clients."""

    def generate_structured(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        response_schema: Mapping[str, object],
    ) -> StructuredGeneration:
        ...

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        ...


def _token_count(value: object) -> int:
    if isinstance(value, str):
        return len(value.split())
    if isinstance(value, Mapping):
        return sum(_token_count(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_token_count(item) for item in value)
    return 0


def _usage_from_payload(payload: Mapping[str, object]) -> LLMUsage:
    raw_usage = payload.get("usage")
    usage = raw_usage if isinstance(raw_usage, Mapping) else {}

    def token_value(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return 0

    input_tokens = token_value("prompt_tokens", "input_tokens")
    output_tokens = token_value("completion_tokens", "output_tokens")
    total_tokens = token_value("total_tokens") or input_tokens + output_tokens
    return LLMUsage(input_tokens, output_tokens, total_tokens)


def _default_structured_request(
    model: str,
    messages: Sequence[Mapping[str, object]],
    response_schema: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        "model": model,
        "messages": list(messages),
        "response_format": dict(response_schema),
    }


def _default_structured_response(payload: Mapping[str, object]) -> Mapping[str, object]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise LLMServiceError()
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise LLMServiceError()
    content = message.get("content")
    if isinstance(content, Mapping):
        return dict(content)
    if not isinstance(content, str):
        raise LLMServiceError()
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        raise LLMServiceError() from None
    if not isinstance(value, Mapping):
        raise LLMServiceError()
    return dict(value)


class FakeLLMClient:
    """Deterministic in-process client used by tests; it never opens HTTP."""

    def __init__(
        self,
        *,
        structured_outputs: Sequence[Mapping[str, object]] = (),
        embedding_dimensions: int = 8,
    ) -> None:
        if embedding_dimensions < 1:
            raise ValueError("embedding_dimensions must be positive")
        self._structured_outputs = tuple(dict(output) for output in structured_outputs)
        self._embedding_dimensions = embedding_dimensions
        self._structured_index = 0

    def generate_structured(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        response_schema: Mapping[str, object],
    ) -> StructuredGeneration:
        if self._structured_outputs:
            output = self._structured_outputs[
                min(self._structured_index, len(self._structured_outputs) - 1)
            ]
            self._structured_index += 1
        else:
            output = {}
        return StructuredGeneration(
            value=dict(output),
            usage=LLMUsage(
                input_tokens=_token_count(messages) + _token_count(response_schema),
                output_tokens=_token_count(output),
                total_tokens=(
                    _token_count(messages) + _token_count(response_schema) + _token_count(output)
                ),
            ),
        )

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not all(isinstance(text, str) for text in texts):
            raise TypeError("texts must contain only strings")
        vectors = tuple(
            tuple(byte / 255 for byte in sha256(text.encode("utf-8")).digest()[: self._embedding_dimensions])
            for text in texts
        )
        input_tokens = sum(_token_count(text) for text in texts)
        return EmbeddingResult(
            vectors=vectors,
            usage=LLMUsage(input_tokens=input_tokens, output_tokens=0, total_tokens=input_tokens),
        )


class OpenAICompatibleLLMClient:
    """Explicitly configured HTTP client for an approved internal gateway."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        structured_endpoint: str,
        embedding_endpoint: str,
        pii_approved: bool,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout_s: float = 30.0,
        max_attempts: int = 3,
        backoff_base_s: float = 0.5,
        structured_request_builder: StructuredRequestBuilder = _default_structured_request,
        structured_response_parser: StructuredResponseParser = _default_structured_response,
    ) -> None:
        if not isinstance(settings, LLMSettings) or not all(
            isinstance(value, str) and value.strip()
            for value in (
                settings.api_key,
                settings.base_url,
                settings.label_model,
                settings.embed_model,
            )
        ):
            raise LLMConfigurationError()
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
        if not _is_relative_endpoint(structured_endpoint) or not _is_relative_endpoint(
            embedding_endpoint
        ):
            raise LLMConfigurationError()
        if not isinstance(pii_approved, bool):
            raise ValueError("pii_approved must be a boolean")
        if not 0 < timeout_s <= 120:
            raise ValueError("timeout_s must be between zero and 120 seconds")
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if backoff_base_s < 0:
            raise ValueError("backoff_base_s must not be negative")

        self._settings = settings
        self._structured_endpoint = structured_endpoint
        self._embedding_endpoint = embedding_endpoint
        self._pii_approved = pii_approved
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._structured_request_builder = structured_request_builder
        self._structured_response_parser = structured_response_parser
        self._client = httpx.Client(
            base_url=settings.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=httpx.Timeout(timeout_s),
            verify=True,
            follow_redirects=False,
            transport=transport,
        )
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

    def close(self) -> None:
        if self._embed_client is not self._client:
            self._embed_client.close()
        self._client.close()

    def __enter__(self) -> OpenAICompatibleLLMClient:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def generate_structured(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        response_schema: Mapping[str, object],
    ) -> StructuredGeneration:
        self._require_pii_approval()
        try:
            request_payload = self._structured_request_builder(
                self._settings.label_model, messages, response_schema
            )
        except Exception:
            raise LLMServiceError() from None
        payload = self._post(self._structured_endpoint, request_payload)
        try:
            value = self._structured_response_parser(payload)
        except LLMServiceError:
            raise
        except Exception:
            raise LLMServiceError() from None
        return StructuredGeneration(value=dict(value), usage=_usage_from_payload(payload))

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

    def _require_pii_approval(self) -> None:
        if not self._pii_approved:
            raise PIIApprovalRequiredError()

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


def _is_relative_endpoint(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and "?" not in value
        and "#" not in value
    )


def _embedding_vectors(
    payload: Mapping[str, object], *, expected_count: int
) -> tuple[tuple[float, ...], ...]:
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != expected_count:
        raise LLMServiceError()
    vectors: list[tuple[float, ...]] = []
    for item in data:
        if not isinstance(item, Mapping):
            raise LLMServiceError()
        embedding = item.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise LLMServiceError()
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in embedding
        ):
            raise LLMServiceError()
        vectors.append(tuple(float(value) for value in embedding))
    return tuple(vectors)


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
