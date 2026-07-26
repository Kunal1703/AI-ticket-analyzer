"""
Best-effort context retrieval for the analyze path (M5.2).

Builds the retriever that ``run_analysis`` calls to ground a tenant's analysis in
its knowledge base. Retrieval is **best-effort**: it opens its own session (like
``persist_analysis``/``resolve_ticket_id``), swallows every error, and returns
``None`` on any failure — so a broken/empty knowledge base or a down embedding
provider degrades to an ungrounded analysis and never breaks the response.

Enabled only when ``rag_enabled`` is set, a database is configured, and an
embedding provider was built; otherwise the factory returns ``None`` and the
analyze path behaves exactly as before.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.vector_store import SqlAlchemyVectorStore
from app.embeddings.base import EmbeddingProvider
from app.observability import metrics
from app.rag.service import RagService

logger = logging.getLogger(__name__)

# (organization_id, query) -> grounding context string, or None when unavailable.
ContextRetriever = Callable[[uuid.UUID, str], Awaitable[str | None]]


def format_context(snippets: list[str]) -> str:
    """Render retrieved chunk texts into a compact, numbered context block."""
    return "\n\n".join(f"[{index}] {text}" for index, text in enumerate(snippets, start=1))


def build_context_retriever(
    *,
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    embedding_provider: EmbeddingProvider | None,
    settings: Settings,
) -> ContextRetriever | None:
    """Return a best-effort retriever, or ``None`` when RAG is not active.

    ``None`` (RAG disabled / no DB / no embeddings) means ``run_analysis`` skips
    retrieval entirely — identical to the pre-M5.2 behavior.
    """
    if not settings.rag_enabled or sessionmaker is None or embedding_provider is None:
        return None

    async def _retrieve(organization_id: uuid.UUID, query: str) -> str | None:
        try:
            async with sessionmaker() as session:
                service = RagService(
                    SqlAlchemyVectorStore(session),
                    embedding_provider,
                    chunk_size=settings.rag_chunk_size,
                    chunk_overlap=settings.rag_chunk_overlap,
                    top_k=settings.rag_top_k,
                    max_candidates=settings.rag_max_candidates,
                    min_score=settings.rag_min_score,
                )
                chunks = await service.retrieve(organization_id=organization_id, query=query)
            if not chunks:
                metrics.record_rag_retrieval("empty")
                return None
            metrics.record_rag_retrieval("grounded")
            return format_context([chunk.content for chunk in chunks])
        except Exception:
            # Retrieval must never break the analyze response (best-effort).
            logger.exception("RAG retrieval failed (best-effort, ignoring)")
            metrics.record_rag_retrieval("error")
            return None

    return _retrieve
