"""
Tests for the pure RAG helpers + schema (M5.2): chunking, cosine similarity /
top-k ranking, and the documents/document_chunks model registration. All offline.
"""

import pytest
from app.rag.chunking import chunk_text
from app.rag.similarity import cosine_similarity, top_k_indices

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_short_text_is_one_chunk(self) -> None:
        assert chunk_text("hello world", chunk_size=200) == ["hello world"]

    def test_empty_or_whitespace_returns_empty(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   \n  ") == []

    def test_splits_into_overlapping_chunks(self) -> None:
        words = [f"w{i}" for i in range(10)]
        chunks = chunk_text(" ".join(words), chunk_size=4, overlap=1)
        # step = 4 - 1 = 3 -> starts at 0, 3, 6 (last covers the tail, no tiny chunk)
        assert chunks == ["w0 w1 w2 w3", "w3 w4 w5 w6", "w6 w7 w8 w9"]

    def test_no_overlap(self) -> None:
        chunks = chunk_text("a b c d e", chunk_size=2, overlap=0)
        assert chunks == ["a b", "c d", "e"]

    def test_overlap_clamped_below_chunk_size(self) -> None:
        # overlap >= chunk_size would stall; it is clamped so progress is made.
        chunks = chunk_text("a b c d", chunk_size=2, overlap=5)
        assert chunks == ["a b", "b c", "c d"]

    def test_invalid_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            chunk_text("a b c", chunk_size=0)

    def test_every_word_is_covered(self) -> None:
        words = [f"t{i}" for i in range(23)]
        chunks = chunk_text(" ".join(words), chunk_size=5, overlap=2)
        seen = {w for chunk in chunks for w in chunk.split()}
        assert seen == set(words)


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_length_mismatch_is_zero(self) -> None:
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_empty_is_zero(self) -> None:
        assert cosine_similarity([], []) == 0.0

    def test_zero_vector_is_zero(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestTopKIndices:
    def test_ranks_by_descending_score(self) -> None:
        query = [1.0, 0.0]
        candidates = [[0.0, 1.0], [1.0, 0.0], [0.9, 0.1]]
        result = top_k_indices(query, candidates, k=2)
        assert [i for i, _ in result] == [1, 2]  # exact match first, then near

    def test_respects_k(self) -> None:
        query = [1.0, 0.0]
        candidates = [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]]
        assert len(top_k_indices(query, candidates, k=1)) == 1

    def test_k_zero_returns_empty(self) -> None:
        assert top_k_indices([1.0], [[1.0]], k=0) == []

    def test_min_score_filters_irrelevant(self) -> None:
        query = [1.0, 0.0]
        candidates = [[0.0, 1.0], [1.0, 0.0]]  # first is orthogonal (score 0.0)
        result = top_k_indices(query, candidates, k=5, min_score=0.0)
        assert [i for i, _ in result] == [1]

    def test_no_candidates(self) -> None:
        assert top_k_indices([1.0], [], k=3) == []


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestRagSchema:
    def test_tables_registered(self) -> None:
        from app.db.base import Base

        assert {"documents", "document_chunks"} <= set(Base.metadata.tables)

    def test_chunk_columns(self) -> None:
        from app.db.models import DocumentChunk

        assert {"organization_id", "document_id", "chunk_index", "content", "embedding"} <= set(
            DocumentChunk.__table__.columns.keys()
        )
