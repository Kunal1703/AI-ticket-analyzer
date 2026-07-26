"""
Tests for the SqlAlchemy vector store (M5.2): mocked-session unit tests (no DB)
plus a skipif round-trip that exercises real queries when DATABASE_URL is set.
"""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.models import Document, DocumentChunk
from app.db.vector_store import SqlAlchemyVectorStore
from app.rag.base import PreparedChunk

DB_URL = os.environ.get("DATABASE_URL")
ORG = uuid.uuid4()


class TestSqlAlchemyVectorStoreMocked:
    @pytest.mark.anyio
    async def test_create_document_flushes(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyVectorStore(session)
        doc = await store.create_document(
            organization_id=ORG, title="Refunds", content="how to refund", source="manual"
        )
        assert doc.title == "Refunds"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.anyio
    async def test_add_chunks_adds_each_and_returns_count(self) -> None:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        store = SqlAlchemyVectorStore(session)
        chunks = [
            PreparedChunk(index=0, content="a", embedding=[0.1]),
            PreparedChunk(index=1, content="b", embedding=[0.2]),
        ]
        added = await store.add_chunks(organization_id=ORG, document_id=uuid.uuid4(), chunks=chunks)
        assert added == 2
        assert session.add.call_count == 2
        session.flush.assert_awaited_once()

    @pytest.mark.anyio
    async def test_list_documents_returns_scalars(self) -> None:
        rows = [Document(organization_id=ORG, title="t", content="c", source="manual")]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyVectorStore(session)
        assert list(await store.list_documents(ORG, limit=10, offset=0)) == rows

    @pytest.mark.anyio
    async def test_count_documents(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one.return_value = 7
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyVectorStore(session)
        assert await store.count_documents(ORG) == 7

    @pytest.mark.anyio
    async def test_get_document_returns_first(self) -> None:
        doc = Document(organization_id=ORG, title="t", content="c", source="manual")
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = doc
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyVectorStore(session)
        assert await store.get_document(ORG, uuid.uuid4()) is doc

    @pytest.mark.anyio
    async def test_count_chunks(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.scalar_one.return_value = 3
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyVectorStore(session)
        assert await store.count_chunks(ORG, uuid.uuid4()) == 3

    @pytest.mark.anyio
    async def test_delete_document_rowcount(self) -> None:
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
        store = SqlAlchemyVectorStore(session)
        assert await store.delete_document(ORG, uuid.uuid4()) is True
        session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        assert await store.delete_document(ORG, uuid.uuid4()) is False

    @pytest.mark.anyio
    async def test_list_chunks_for_org_returns_scalars(self) -> None:
        rows = [
            DocumentChunk(
                organization_id=ORG,
                document_id=uuid.uuid4(),
                chunk_index=0,
                content="a",
                embedding=[0.1, 0.2],
            )
        ]
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=result)
        store = SqlAlchemyVectorStore(session)
        assert list(await store.list_chunks_for_org(ORG, limit=100)) == rows


class TestVectorStoreRoundTrip:
    @pytest.mark.anyio
    @pytest.mark.skipif(not DB_URL, reason="DATABASE_URL not set; skipping DB integration test")
    async def test_document_and_chunk_lifecycle(self) -> None:
        from app.db.base import Base
        from app.db.models import Organization
        from app.db.session import create_db_engine, create_sessionmaker

        assert DB_URL is not None  # guaranteed by skipif
        engine = create_db_engine(DB_URL)
        sessionmaker = create_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessionmaker() as session:
                org = Organization(name="Acme", slug="acme-rag")
                session.add(org)
                await session.flush()
                store = SqlAlchemyVectorStore(session)
                doc = await store.create_document(
                    organization_id=org.id, title="KB", content="body", source="manual"
                )
                await store.add_chunks(
                    organization_id=org.id,
                    document_id=doc.id,
                    chunks=[PreparedChunk(index=0, content="body", embedding=[0.1, 0.2])],
                )
                await session.commit()
                org_id, doc_id = org.id, doc.id

            async with sessionmaker() as session:
                store = SqlAlchemyVectorStore(session)
                assert await store.count_documents(org_id) == 1
                assert [d.id for d in await store.list_documents(org_id, limit=10, offset=0)] == [
                    doc_id
                ]
                assert await store.count_chunks(org_id, doc_id) == 1
                chunks = await store.list_chunks_for_org(org_id, limit=10)
                assert [c.embedding for c in chunks] == [[0.1, 0.2]]
                # Cross-org isolation.
                assert await store.get_document(uuid.uuid4(), doc_id) is None
                assert await store.delete_document(org_id, doc_id) is True
                await session.commit()
                assert await store.count_documents(org_id) == 0
        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()
