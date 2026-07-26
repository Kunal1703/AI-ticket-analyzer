"""
Retrieval-Augmented Generation (RAG) for AI Ticket Analyzer (M5.2).

Grounds analyses in a tenant's knowledge-base documents (and, later, past
tickets): documents are chunked (:mod:`app.rag.chunking`), embedded via the
provider-agnostic :mod:`app.embeddings` layer, and stored tenant-scoped behind a
``VectorStore`` port; retrieval ranks a query's nearest chunks
(:mod:`app.rag.similarity`) and feeds them as context into ``run_analysis``.

Everything is tenant-isolated (every vector is scoped by ``organization_id``) and
retrieval into the analyze path is best-effort (a failure degrades to no context,
never breaking analysis).
"""

from app.rag.base import PreparedChunk, VectorStore
from app.rag.chunking import chunk_text
from app.rag.similarity import cosine_similarity, top_k_indices

# Note: ``service`` and ``retrieval`` are intentionally NOT re-exported here.
# They (indirectly) import ``app.db.vector_store``, which imports back into this
# package — eager re-exports would create an import cycle. Import them from their
# modules directly (``app.rag.service`` / ``app.rag.retrieval``).
__all__ = [
    "PreparedChunk",
    "VectorStore",
    "chunk_text",
    "cosine_similarity",
    "top_k_indices",
]
