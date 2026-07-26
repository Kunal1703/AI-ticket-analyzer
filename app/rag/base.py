"""
Vector store port for RAG (M5.2).

``VectorStore`` is the persistence port the knowledge-base + retrieval layer
depends on (mirroring ``TicketStore``/``RoutingRuleStore``), so routes/services
are testable against an in-memory fake with no database. Every method is
tenant-scoped by ``organization_id``.

Similarity ranking is intentionally **not** on this port — the store returns a
tenant's candidate chunks and the pure :mod:`app.rag.similarity` helpers rank
them (the same "store loads rows, pure engine evaluates" split as routing). A
pgvector/ANN index would later push ranking into ``search`` without changing the
port's shape.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.db.models import Document, DocumentChunk


@dataclass(frozen=True)
class PreparedChunk:
    """A chunk ready to persist: its position, text, and embedding vector."""

    index: int
    content: str
    embedding: list[float]


class VectorStore(Protocol):
    """Tenant-scoped persistence port for KB documents and their embedded chunks."""

    async def create_document(
        self, *, organization_id: uuid.UUID, title: str, content: str, source: str
    ) -> Document: ...

    async def add_chunks(
        self,
        *,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: Sequence[PreparedChunk],
    ) -> int: ...

    async def list_documents(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Document]: ...

    async def count_documents(self, organization_id: uuid.UUID) -> int: ...

    async def get_document(
        self, organization_id: uuid.UUID, document_id: uuid.UUID
    ) -> Document | None: ...

    async def count_chunks(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> int: ...

    async def delete_document(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> bool: ...

    async def list_chunks_for_org(
        self, organization_id: uuid.UUID, *, limit: int
    ) -> Sequence[DocumentChunk]: ...
