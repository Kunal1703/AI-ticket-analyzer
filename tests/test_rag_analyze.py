"""
Tests for wiring RAG retrieval into the analyze path (M5.2, step 5):
- prompt v2 (context-aware, append-only) + v1 unchanged,
- the provider threading ``context`` into the prompt,
- ``run_analysis`` best-effort retrieval + cache-key namespacing,
- ``build_context_retriever`` (enabled/disabled + best-effort),
- ``/v1/analyze`` grounding end-to-end with a fake provider.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.ai.base import AnalysisResult
from app.cache.base import cache_key
from app.cache.memory import TTLCache
from app.config import Settings
from app.models import TicketAnalysis, TicketCategory, TicketPriority
from app.prompts import get_prompt
from app.rag.retrieval import build_context_retriever, format_context
from app.services.analyze import run_analysis
from httpx import AsyncClient

ORG = uuid.uuid4()


def _analysis() -> TicketAnalysis:
    return TicketAnalysis(
        summary="s",
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        next_actions=["x"],
    )


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.name = "fake"
    provider.model = "fake-model"
    provider.analyze = AsyncMock(return_value=AnalysisResult(analysis=_analysis()))
    return provider


def _chunk(content: str, embedding: list[float]) -> Any:
    """Build a DocumentChunk row for retriever tests."""
    from app.db.models import DocumentChunk

    row = DocumentChunk(
        organization_id=ORG,
        document_id=uuid.uuid4(),
        chunk_index=0,
        content=content,
        embedding=embedding,
    )
    return row


class _FakeSession:
    """Async-context session stand-in returning fixed rows from execute()."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def execute(self, *args: object, **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._rows
        return result


def _sessionmaker_returning(rows: list[Any]) -> MagicMock:
    return MagicMock(return_value=_FakeSession(rows))


# ---------------------------------------------------------------------------
# Prompt versions
# ---------------------------------------------------------------------------


class TestPromptVersions:
    def test_v1_ignores_context(self) -> None:
        v1 = get_prompt("v1")
        assert v1.context_prompt_builder is None
        # v1's user message is identical whether or not context is supplied.
        assert v1.build_user_message("ticket", "some context") == v1.build_user_message("ticket")

    def test_v2_folds_in_context(self) -> None:
        v2 = get_prompt("v2")
        assert v2.version == "v2"
        message = v2.build_user_message("my ticket", "KB excerpt about refunds")
        assert "KB excerpt about refunds" in message
        assert "my ticket" in message
        # Without context, v2 falls back to the plain ticket prompt.
        assert "KNOWLEDGE BASE" not in v2.build_user_message("my ticket")

    def test_v2_messages_shape(self) -> None:
        messages = get_prompt("v2").messages("t", "ctx")
        assert messages[0]["role"] == "system"
        assert "ctx" in messages[1]["content"]


# ---------------------------------------------------------------------------
# run_analysis retrieval wiring
# ---------------------------------------------------------------------------


class TestRunAnalysisRetrieval:
    @pytest.mark.anyio
    async def test_context_passed_to_provider_and_namespaces_cache(self) -> None:
        provider = _provider()
        cache = TTLCache(ttl_seconds=300)

        async def retriever(org_id: uuid.UUID, query: str) -> str | None:
            assert org_id == ORG
            return "grounding context"

        outcome = await run_analysis(
            ticket_text="hello",
            provider=provider,
            cache=cache,
            sessionmaker=None,
            organization_id=ORG,
            retrieve_context=retriever,
        )
        assert outcome.analysis.category == TicketCategory.BILLING
        # Provider received the context.
        assert provider.analyze.await_args.kwargs["context"] == "grounding context"
        # Result cached under the rag-namespaced key, not the plain org key.
        assert await cache.get(f"{ORG}:{cache_key('hello')}") is None

    @pytest.mark.anyio
    async def test_no_retriever_leaves_context_none(self) -> None:
        provider = _provider()
        cache = TTLCache(ttl_seconds=300)
        await run_analysis(
            ticket_text="hello",
            provider=provider,
            cache=cache,
            sessionmaker=None,
            organization_id=ORG,
        )
        assert provider.analyze.await_args.kwargs["context"] is None

    @pytest.mark.anyio
    async def test_retriever_not_called_on_legacy_path(self) -> None:
        provider = _provider()
        cache = TTLCache(ttl_seconds=300)
        called = False

        async def retriever(org_id: uuid.UUID, query: str) -> str | None:
            nonlocal called
            called = True
            return "ctx"

        await run_analysis(
            ticket_text="hello",
            provider=provider,
            cache=cache,
            sessionmaker=None,
            organization_id=None,  # legacy path
            retrieve_context=retriever,
        )
        assert called is False
        assert provider.analyze.await_args.kwargs["context"] is None

    @pytest.mark.anyio
    async def test_empty_context_uses_plain_cache_key(self) -> None:
        provider = _provider()
        cache = TTLCache(ttl_seconds=300)

        async def retriever(org_id: uuid.UUID, query: str) -> str | None:
            return None  # no relevant context

        await run_analysis(
            ticket_text="hello",
            provider=provider,
            cache=cache,
            sessionmaker=None,
            organization_id=ORG,
            retrieve_context=retriever,
        )
        # Cached under the plain org-namespaced key (no rag suffix).
        assert await cache.get(f"{ORG}:{cache_key('hello')}") is not None


# ---------------------------------------------------------------------------
# build_context_retriever
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)


class TestBuildContextRetriever:
    def test_disabled_when_rag_off(self) -> None:
        assert (
            build_context_retriever(
                sessionmaker=MagicMock(), embedding_provider=MagicMock(), settings=_settings()
            )
            is None
        )

    def test_disabled_without_sessionmaker(self) -> None:
        assert (
            build_context_retriever(
                sessionmaker=None,
                embedding_provider=MagicMock(),
                settings=_settings(rag_enabled=True),
            )
            is None
        )

    def test_disabled_without_embeddings(self) -> None:
        assert (
            build_context_retriever(
                sessionmaker=MagicMock(),
                embedding_provider=None,
                settings=_settings(rag_enabled=True),
            )
            is None
        )

    def test_format_context_numbers_snippets(self) -> None:
        assert format_context(["a", "b"]) == "[1] a\n\n[2] b"

    @pytest.mark.anyio
    async def test_retriever_is_best_effort_on_error(self) -> None:
        # A sessionmaker that raises when used → retriever swallows and returns None.
        failing_sessionmaker = MagicMock(side_effect=RuntimeError("db down"))
        retriever = build_context_retriever(
            sessionmaker=failing_sessionmaker,
            embedding_provider=MagicMock(),
            settings=_settings(rag_enabled=True),
        )
        assert retriever is not None
        assert await retriever(ORG, "query") is None

    @pytest.mark.anyio
    async def test_retriever_grounds_from_chunks(self) -> None:
        from app.embeddings.config import EmbeddingConfig
        from app.embeddings.hash_provider import HashEmbeddingProvider, hash_embed

        embedder = HashEmbeddingProvider(
            EmbeddingConfig(provider="hash", model="hash", dimensions=64)
        )
        chunk = _chunk("refund billing help", hash_embed("refund billing help", 64))
        retriever = build_context_retriever(
            sessionmaker=_sessionmaker_returning([chunk]),
            embedding_provider=embedder,
            settings=_settings(rag_enabled=True, embedding_dimensions=64),
        )
        assert retriever is not None
        context = await retriever(ORG, "refund billing help")
        assert context is not None
        assert "refund billing help" in context

    @pytest.mark.anyio
    async def test_retriever_returns_none_when_no_chunks(self) -> None:
        from app.embeddings.config import EmbeddingConfig
        from app.embeddings.hash_provider import HashEmbeddingProvider

        embedder = HashEmbeddingProvider(EmbeddingConfig(provider="hash", model="hash"))
        retriever = build_context_retriever(
            sessionmaker=_sessionmaker_returning([]),  # no chunks for this org
            embedding_provider=embedder,
            settings=_settings(rag_enabled=True),
        )
        assert retriever is not None
        assert await retriever(ORG, "anything") is None


# ---------------------------------------------------------------------------
# Endpoint integration (/v1/analyze grounded)
# ---------------------------------------------------------------------------


class TestAnalyzeEndpointGrounding:
    @pytest.mark.anyio
    async def test_v1_analyze_uses_retriever(
        self, client: AsyncClient, override_provider: Any
    ) -> None:
        from app.dependencies import get_context_retriever, require_quota
        from app.main import app
        from app.tenancy.base import TenantContext

        provider = _provider()
        override_provider(provider)

        async def retriever(org_id: uuid.UUID, query: str) -> str | None:
            return "relevant KB context"

        context = TenantContext(organization_id=ORG, principal_type="api_key", scopes=("analyze",))
        app.dependency_overrides[require_quota] = lambda: context
        app.dependency_overrides[get_context_retriever] = lambda: retriever
        try:
            resp = await client.post("/v1/analyze", json={"ticket": "please help with billing"})
            assert resp.status_code == 200
            assert resp.json()["category"] == "Billing"
            assert provider.analyze.await_args.kwargs["context"] == "relevant KB context"
        finally:
            app.dependency_overrides.pop(require_quota, None)
            app.dependency_overrides.pop(get_context_retriever, None)
