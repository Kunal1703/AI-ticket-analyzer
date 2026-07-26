"""SQLAlchemy implementation of the RAG vector store (M5.2).

Works with either a request-scoped session (KB management routes) or a
self-contained session opened from the sessionmaker (best-effort retrieval on the
analyze path) — the caller owns the session lifecycle, this class just issues the
tenant-scoped queries.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.rag.base import PreparedChunk


class SqlAlchemyVectorStore:
    """Vector/KB persistence via a provided async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_document(
        self, *, organization_id: uuid.UUID, title: str, content: str, source: str
    ) -> Document:
        document = Document(
            organization_id=organization_id, title=title, content=content, source=source
        )
        self._session.add(document)
        await self._session.flush()  # populate document.id for the chunk FK
        return document

    async def add_chunks(
        self,
        *,
        organization_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: Sequence[PreparedChunk],
    ) -> int:
        for chunk in chunks:
            self._session.add(
                DocumentChunk(
                    organization_id=organization_id,
                    document_id=document_id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    embedding=chunk.embedding,
                )
            )
        await self._session.flush()
        return len(chunks)

    async def list_documents(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> Sequence[Document]:
        result = await self._session.execute(
            select(Document)
            .where(Document.organization_id == organization_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_documents(self, organization_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == organization_id)
        )
        return int(result.scalar_one())

    async def get_document(
        self, organization_id: uuid.UUID, document_id: uuid.UUID
    ) -> Document | None:
        result = await self._session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        return result.scalars().first()

    async def count_chunks(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.organization_id == organization_id,
                DocumentChunk.document_id == document_id,
            )
        )
        return int(result.scalar_one())

    async def delete_document(self, organization_id: uuid.UUID, document_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        return result.rowcount > 0

    async def list_chunks_for_org(
        self, organization_id: uuid.UUID, *, limit: int
    ) -> Sequence[DocumentChunk]:
        """Return a tenant's chunks (capped) as retrieval candidates.

        Ordered newest-first and bounded by ``limit`` so a very large knowledge
        base doesn't load unbounded rows; ranking happens in ``app.rag.similarity``.
        """
        result = await self._session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.organization_id == organization_id)
            .order_by(DocumentChunk.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
