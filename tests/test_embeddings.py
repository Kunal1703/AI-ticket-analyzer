"""
Tests for the embedding provider abstraction (M5.2).

Covers the keyless deterministic ``hash`` provider, the OpenAI-SDK provider
(success + error translation via a mocked client, no network), and the
factory/registry (defaults, key fallback, validation). Everything runs offline.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.config import Settings
from app.embeddings.base import (
    EmbeddingConnectionError,
    EmbeddingProvider,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
)
from app.embeddings.config import EmbeddingConfig
from app.embeddings.factory import (
    available_embedding_providers,
    build_embedding_config,
    build_embedding_provider,
)
from app.embeddings.hash_provider import HashEmbeddingProvider, hash_embed
from app.embeddings.openai_provider import OpenAIEmbeddingProvider
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Hash provider (deterministic, keyless)
# ---------------------------------------------------------------------------


class TestHashEmbeddingProvider:
    @pytest.mark.anyio
    async def test_deterministic_and_correct_dimension(self) -> None:
        provider = HashEmbeddingProvider(
            EmbeddingConfig(provider="hash", model="hash", dimensions=64)
        )
        first = await provider.embed(["password reset please"])
        second = await provider.embed(["password reset please"])
        assert first == second
        assert len(first) == 1
        assert len(first[0]) == 64

    @pytest.mark.anyio
    async def test_embed_batch_and_embed_one(self) -> None:
        provider = HashEmbeddingProvider(
            EmbeddingConfig(provider="hash", model="hash", dimensions=32)
        )
        vectors = await provider.embed(["alpha", "beta"])
        assert len(vectors) == 2
        one = await provider.embed_one("alpha")
        assert one == vectors[0]
        assert provider.name == "hash"
        assert provider.model == "hash"

    @pytest.mark.anyio
    async def test_empty_input_returns_empty(self) -> None:
        provider = HashEmbeddingProvider(EmbeddingConfig(provider="hash", model="hash"))
        assert await provider.embed([]) == []

    def test_normalized_unit_length(self) -> None:
        vector = hash_embed("some meaningful text here", 128)
        norm = sum(component * component for component in vector) ** 0.5
        assert norm == pytest.approx(1.0)

    def test_no_tokens_returns_zero_vector(self) -> None:
        vector = hash_embed("!!! ???", 16)
        assert vector == [0.0] * 16

    def test_similar_texts_are_closer_than_dissimilar(self) -> None:
        def cosine(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b, strict=True))

        base = hash_embed("cannot log in to my account", 256)
        near = hash_embed("i cannot log in to the account", 256)
        far = hash_embed("please cancel my subscription and refund", 256)
        assert cosine(base, near) > cosine(base, far)


# ---------------------------------------------------------------------------
# OpenAI embedding provider (mocked SDK — no network)
# ---------------------------------------------------------------------------


def _config(**overrides: Any) -> EmbeddingConfig:
    base: dict[str, Any] = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "api_key": "sk-x",
    }
    base.update(overrides)
    return EmbeddingConfig(**base)


def _provider_with_create(create_mock: AsyncMock, **overrides: Any) -> OpenAIEmbeddingProvider:
    provider = OpenAIEmbeddingProvider(_config(**overrides))
    client = MagicMock()
    client.embeddings.create = create_mock
    provider._client = client  # inject mock so no real client/network is used
    return provider


def _embeddings_response(vectors: list[list[float]]) -> MagicMock:
    response = MagicMock()
    response.data = [MagicMock(embedding=v) for v in vectors]
    return response


class TestOpenAIEmbeddingProvider:
    @pytest.mark.anyio
    async def test_embed_returns_vectors(self) -> None:
        create = AsyncMock(return_value=_embeddings_response([[0.1, 0.2], [0.3, 0.4]]))
        provider = _provider_with_create(create)
        vectors = await provider.embed(["a", "b"])
        assert vectors == [[0.1, 0.2], [0.3, 0.4]]
        assert provider.name == "openai"
        assert provider.model == "text-embedding-3-small"

    @pytest.mark.anyio
    async def test_empty_input_short_circuits(self) -> None:
        create = AsyncMock()
        provider = _provider_with_create(create)
        assert await provider.embed([]) == []
        create.assert_not_called()

    @pytest.mark.anyio
    async def test_length_mismatch_is_response_error(self) -> None:
        create = AsyncMock(return_value=_embeddings_response([[0.1, 0.2]]))
        provider = _provider_with_create(create)
        with pytest.raises(EmbeddingResponseError):
            await provider.embed(["a", "b"])

    @pytest.mark.anyio
    async def test_timeout_translated(self) -> None:
        create = AsyncMock(side_effect=APITimeoutError(request=httpx.Request("POST", "http://x")))
        provider = _provider_with_create(create, max_retries=1)
        with pytest.raises(EmbeddingTimeoutError):
            await provider.embed(["a"])

    @pytest.mark.anyio
    async def test_rate_limit_translated(self) -> None:
        response = httpx.Response(429, request=httpx.Request("POST", "http://x"))
        create = AsyncMock(side_effect=RateLimitError("rate", response=response, body=None))
        provider = _provider_with_create(create, max_retries=1)
        with pytest.raises(EmbeddingRateLimitError):
            await provider.embed(["a"])

    @pytest.mark.anyio
    async def test_connection_error_translated(self) -> None:
        create = AsyncMock(
            side_effect=APIConnectionError(request=httpx.Request("POST", "http://x"))
        )
        provider = _provider_with_create(create, max_retries=1)
        with pytest.raises(EmbeddingConnectionError):
            await provider.embed(["a"])

    @pytest.mark.anyio
    async def test_status_error_translated(self) -> None:
        response = httpx.Response(500, request=httpx.Request("POST", "http://x"))
        create = AsyncMock(side_effect=APIStatusError("boom", response=response, body=None))
        provider = _provider_with_create(create)
        with pytest.raises(EmbeddingConnectionError):
            await provider.embed(["a"])

    @pytest.mark.anyio
    async def test_aclose_closes_client(self) -> None:
        provider = OpenAIEmbeddingProvider(_config())
        client = MagicMock()
        client.close = AsyncMock()
        provider._client = client
        await provider.aclose()
        client.close.assert_awaited_once()
        assert provider._client is None

    @pytest.mark.anyio
    async def test_get_client_builds_once(self) -> None:
        provider = OpenAIEmbeddingProvider(_config(api_key=None))
        client = provider._get_client()
        assert provider._get_client() is client


# ---------------------------------------------------------------------------
# Factory / registry
# ---------------------------------------------------------------------------


class TestEmbeddingFactory:
    def test_available_providers(self) -> None:
        names = available_embedding_providers()
        assert {"openai", "ollama", "openai-compatible", "hash"} <= set(names)

    def test_build_openai_uses_defaults(self) -> None:
        provider = build_embedding_provider(
            _settings(embedding_provider="openai", llm_api_key="sk-x")
        )
        assert provider.name == "openai"
        assert provider.model == "text-embedding-3-small"

    def test_api_key_falls_back_to_llm_key(self) -> None:
        config = build_embedding_config(
            _settings(embedding_provider="openai", llm_api_key="sk-llm")
        )
        assert config.api_key == "sk-llm"

    def test_explicit_embedding_key_wins(self) -> None:
        config = build_embedding_config(
            _settings(embedding_provider="openai", embedding_api_key="sk-emb", llm_api_key="sk-llm")
        )
        assert config.api_key == "sk-emb"

    def test_hash_provider_needs_no_key(self) -> None:
        provider = build_embedding_provider(_settings(embedding_provider="hash"))
        assert isinstance(provider, HashEmbeddingProvider)
        assert provider.model == "hash"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported embedding provider"):
            build_embedding_config(_settings(embedding_provider="nope"))

    def test_openai_without_key_raises(self) -> None:
        with pytest.raises(ValueError, match="requires an API key"):
            build_embedding_config(_settings(embedding_provider="openai", llm_api_key=None))

    def test_openai_compatible_requires_base_url(self) -> None:
        with pytest.raises(ValueError, match="requires a base URL"):
            build_embedding_config(
                _settings(embedding_provider="openai-compatible", embedding_model="m")
            )

    def test_openai_compatible_requires_model(self) -> None:
        with pytest.raises(ValueError, match="requires a model"):
            build_embedding_config(_settings(embedding_provider="openai-compatible"))

    def test_provider_is_embedding_provider(self) -> None:
        provider = build_embedding_provider(_settings(embedding_provider="hash"))
        assert isinstance(provider, EmbeddingProvider)
