"""
Tests for the RAG service + knowledge-base endpoints (M5.2).

Uses an in-memory ``FakeVectorStore`` and the keyless ``hash`` embedding provider,
so ingestion/retrieval run deterministically with no DB and no live LLM.
"""

import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from app.config import Settings
from app.db.models import Document, DocumentChunk
from app.embeddings.base import EmbeddingError, EmbeddingProvider
from app.embeddings.config import EmbeddingConfig
from app.embeddings.hash_provider import HashEmbeddingProvider
from app.rag.base import PreparedChunk
from app.rag.service import RagService
from httpx import AsyncClient

ORG = uuid.uuid4()


def _hash_provider() -> HashEmbeddingProvider:
    return HashEmbeddingProvider(EmbeddingConfig(provider="hash", model="hash", dimensions=128))


class FailingEmbeddingProvider(EmbeddingProvider):
    @property
    def name(self) -> str:
        return "failing"

    @property
    def model(self) -> str:
        return "failing"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingError("boom")


class FakeVectorStore:
    """In-memory VectorStore for offline service/route tests."""

    def __init__(self) -> None:
        self.documents: list[Document] = []
        self.chunks: list[DocumentChunk] = []

    async def create_document(
        self, *, organization_id: uuid.UUID, title: str, content: str, source: str
    ) -> Document:
        doc = Document(organization_id=organization_id, title=title, content=content, source=source)
        doc.id = uuid.uuid4()
        doc.created_at = datetime.now(UTC)
        self.documents.append(doc)
        return doc

    async def add_chunks(
        self,
        *,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: Sequence[PreparedChunk],
    ) -> int:
        for chunk in chunks:
            row = DocumentChunk(
                organization_id=organization_id,
                document_id=document_id,
                chunk_index=chunk.index,
                content=chunk.content,
                embedding=chunk.embedding,
            )
            row.created_at = datetime.now(UTC)
            self.chunks.append(row)
        return len(chunks)

    async def list_documents(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Document]:
        rows = [d for d in self.documents if d.organization_id == organization_id]
        return rows[offset : offset + limit]

    async def count_documents(self, organization_id: uuid.UUID) -> int:
        return len([d for d in self.documents if d.organization_id == organization_id])

    async def get_document(
        self, organization_id: uuid.UUID, document_id: uuid.UUID
    ) -> Document | None:
        for d in self.documents:
            if d.id == document_id and d.organization_id == organization_id:
                return d
        return None

    async def count_chunks(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> int:
        return len(
            [
                c
                for c in self.chunks
                if c.document_id == document_id and c.organization_id == organization_id
            ]
        )

    async def delete_document(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> bool:
        before = len(self.documents)
        self.documents = [
            d
            for d in self.documents
            if not (d.id == document_id and d.organization_id == organization_id)
        ]
        return len(self.documents) < before

    async def list_chunks_for_org(
        self, organization_id: uuid.UUID, *, limit: int
    ) -> Sequence[DocumentChunk]:
        rows = [c for c in self.chunks if c.organization_id == organization_id]
        return rows[:limit]


def _service(store: FakeVectorStore, embedder: EmbeddingProvider | None = None) -> RagService:
    return RagService(
        store,
        embedder or _hash_provider(),
        chunk_size=50,
        chunk_overlap=10,
        top_k=3,
        max_candidates=100,
        min_score=0.0,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TestRagService:
    @pytest.mark.anyio
    async def test_ingest_chunks_and_embeds(self) -> None:
        store = FakeVectorStore()
        service = _service(store)
        content = " ".join(f"word{i}" for i in range(120))
        document, chunk_count = await service.ingest(
            organization_id=ORG, title="Guide", content=content, source="manual"
        )
        assert chunk_count >= 2  # 120 words / chunk_size 50 with overlap
        assert len(store.chunks) == chunk_count
        assert all(len(c.embedding) == 128 for c in store.chunks)
        assert document.title == "Guide"

    @pytest.mark.anyio
    async def test_ingest_blank_content_stores_zero_chunks(self) -> None:
        store = FakeVectorStore()
        service = _service(store)
        _document, chunk_count = await service.ingest(
            organization_id=ORG, title="Empty", content="   ", source="manual"
        )
        assert chunk_count == 0
        assert store.chunks == []

    @pytest.mark.anyio
    async def test_retrieve_ranks_relevant_chunk_first(self) -> None:
        store = FakeVectorStore()
        service = _service(store)
        await service.ingest(
            organization_id=ORG,
            title="Refunds",
            content="To request a refund open billing settings and click refund.",
            source="manual",
        )
        await service.ingest(
            organization_id=ORG,
            title="Login",
            content="If you cannot log in reset your password from the account page.",
            source="manual",
        )
        results = await service.retrieve(
            organization_id=ORG, query="how do I get a refund for billing", k=1
        )
        assert len(results) == 1
        assert "refund" in results[0].content.lower()
        assert results[0].score > 0.0

    @pytest.mark.anyio
    async def test_retrieve_blank_query_returns_empty(self) -> None:
        store = FakeVectorStore()
        service = _service(store)
        assert await service.retrieve(organization_id=ORG, query="   ") == []

    @pytest.mark.anyio
    async def test_retrieve_is_tenant_scoped(self) -> None:
        store = FakeVectorStore()
        service = _service(store)
        await service.ingest(
            organization_id=ORG, title="Doc", content="refund billing help", source="manual"
        )
        # A different org sees nothing.
        assert await service.retrieve(organization_id=uuid.uuid4(), query="refund") == []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def rag_overrides() -> Generator[dict[str, Any], None, None]:
    from app.dependencies import (
        get_rag_service,
        get_vector_store,
        require_org_membership,
    )
    from app.main import app
    from app.rag.routes import _require_owner_or_admin

    store = FakeVectorStore()
    state: dict[str, Any] = {"store": store, "embedder": _hash_provider()}

    def _service_override() -> RagService:
        return _service(state["store"], state["embedder"])

    app.dependency_overrides[get_vector_store] = lambda: state["store"]
    app.dependency_overrides[get_rag_service] = _service_override
    app.dependency_overrides[require_org_membership] = lambda: object()
    app.dependency_overrides[_require_owner_or_admin] = lambda: object()
    yield state
    for dep in (get_vector_store, get_rag_service, require_org_membership, _require_owner_or_admin):
        app.dependency_overrides.pop(dep, None)


class TestKnowledgeBaseRoutes:
    @pytest.mark.anyio
    async def test_create_list_get_delete(
        self, client: AsyncClient, rag_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(
            f"/v1/orgs/{ORG}/documents",
            json={"title": "Refund policy", "content": "Refunds are issued within 7 days."},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "Refund policy"
        assert body["chunk_count"] >= 1
        doc_id = body["id"]

        listed = await client.get(f"/v1/orgs/{ORG}/documents")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        detail = await client.get(f"/v1/orgs/{ORG}/documents/{doc_id}")
        assert detail.status_code == 200
        assert detail.json()["content"] == "Refunds are issued within 7 days."
        assert detail.json()["chunk_count"] >= 1

        deleted = await client.delete(f"/v1/orgs/{ORG}/documents/{doc_id}")
        assert deleted.status_code == 204
        assert (await client.delete(f"/v1/orgs/{ORG}/documents/{doc_id}")).status_code == 404

    @pytest.mark.anyio
    async def test_get_unknown_document_404(
        self, client: AsyncClient, rag_overrides: dict[str, Any]
    ) -> None:
        resp = await client.get(f"/v1/orgs/{ORG}/documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_search_returns_ranked_chunks(
        self, client: AsyncClient, rag_overrides: dict[str, Any]
    ) -> None:
        await client.post(
            f"/v1/orgs/{ORG}/documents",
            json={"title": "Refunds", "content": "Refund requests are processed in billing."},
        )
        await client.post(
            f"/v1/orgs/{ORG}/documents",
            json={"title": "Login", "content": "Reset your password on the account page."},
        )
        resp = await client.get(
            f"/v1/orgs/{ORG}/documents/search", params={"q": "refund billing", "k": 1}
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert "refund" in results[0]["content"].lower()

    @pytest.mark.anyio
    async def test_create_embedding_failure_502(
        self, client: AsyncClient, rag_overrides: dict[str, Any]
    ) -> None:
        rag_overrides["embedder"] = FailingEmbeddingProvider()
        resp = await client.post(
            f"/v1/orgs/{ORG}/documents",
            json={"title": "X", "content": "some content to embed"},
        )
        assert resp.status_code == 502

    @pytest.mark.anyio
    async def test_create_validation_error_422(
        self, client: AsyncClient, rag_overrides: dict[str, Any]
    ) -> None:
        resp = await client.post(f"/v1/orgs/{ORG}/documents", json={"title": "", "content": "x"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------


class TestRagDependencies:
    def test_get_embedding_provider_503_when_none(self) -> None:
        from unittest.mock import MagicMock

        from app.dependencies import get_embedding_provider
        from fastapi import HTTPException

        request = MagicMock()
        request.app.state.embedding_provider = None
        with pytest.raises(HTTPException) as exc:
            get_embedding_provider(request)
        assert exc.value.status_code == 503

    def test_get_embedding_provider_returns_provider(self) -> None:
        from unittest.mock import MagicMock

        from app.dependencies import get_embedding_provider

        provider = _hash_provider()
        request = MagicMock()
        request.app.state.embedding_provider = provider
        assert get_embedding_provider(request) is provider

    def test_get_rag_service_assembles(self) -> None:
        from app.dependencies import get_rag_service

        store = FakeVectorStore()
        service = get_rag_service(
            settings=Settings(_env_file=None),
            vector_store=store,
            embedding_provider=_hash_provider(),
        )
        assert isinstance(service, RagService)

    def test_get_vector_store_wraps_session(self) -> None:
        from app.db.vector_store import SqlAlchemyVectorStore
        from app.dependencies import get_vector_store

        assert isinstance(get_vector_store(session=object()), SqlAlchemyVectorStore)  # type: ignore[arg-type]
