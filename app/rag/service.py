"""
RAG service: knowledge-base ingestion + retrieval (M5.2).

Coordinates the provider-agnostic :mod:`app.embeddings` layer, the pure
chunking/similarity helpers, and the tenant-scoped ``VectorStore`` port. It is
HTTP-free and store/provider-injected, so it is unit-testable with fakes.

- **Ingestion** (``ingest``) is a deliberate management action: chunk → embed →
  store. Embedding failures propagate to the caller (surfaced as an HTTP error).
- **Retrieval** (``retrieve``) is used by the KB search endpoint and, best-effort,
  by the analyze path. It embeds the query, loads the tenant's candidate chunks,
  and ranks them with the pure similarity helpers — always scoped to one org.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.db.models import Document
from app.embeddings.base import EmbeddingProvider
from app.rag.base import PreparedChunk, VectorStore
from app.rag.chunking import chunk_text
from app.rag.similarity import top_k_indices


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieved knowledge-base chunk and its similarity score."""

    document_id: uuid.UUID
    content: str
    score: float


class RagService:
    """Ingest and retrieve tenant knowledge-base content for grounding analyses."""

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        *,
        chunk_size: int,
        chunk_overlap: int,
        top_k: int,
        max_candidates: int,
        min_score: float,
    ) -> None:
        self._store = vector_store
        self._embedder = embedding_provider
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._top_k = top_k
        self._max_candidates = max_candidates
        self._min_score = min_score

    async def ingest(
        self, *, organization_id: uuid.UUID, title: str, content: str, source: str
    ) -> tuple[Document, int]:
        """Chunk, embed, and store a document. Returns the doc + chunk count."""
        chunks = chunk_text(content, chunk_size=self._chunk_size, overlap=self._chunk_overlap)
        document = await self._store.create_document(
            organization_id=organization_id, title=title, content=content, source=source
        )
        if chunks:
            embeddings = await self._embedder.embed(chunks)
            prepared = [
                PreparedChunk(index=index, content=text, embedding=embedding)
                for index, (text, embedding) in enumerate(zip(chunks, embeddings, strict=True))
            ]
            await self._store.add_chunks(
                organization_id=organization_id, document_id=document.id, chunks=prepared
            )
        return document, len(chunks)

    async def retrieve(
        self, *, organization_id: uuid.UUID, query: str, k: int | None = None
    ) -> list[RetrievedChunk]:
        """Return the query's nearest KB chunks for an org (ranked, top-k)."""
        query_text = query.strip()
        if not query_text:
            return []
        query_vector = await self._embedder.embed_one(query_text)
        candidates: Sequence = await self._store.list_chunks_for_org(
            organization_id, limit=self._max_candidates
        )
        ranked = top_k_indices(
            query_vector,
            [candidate.embedding for candidate in candidates],
            k=k if k is not None else self._top_k,
            min_score=self._min_score,
        )
        return [
            RetrievedChunk(
                document_id=candidates[index].document_id,
                content=candidates[index].content,
                score=score,
            )
            for index, score in ranked
        ]
