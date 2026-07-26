"""
Pure vector-similarity ranking for RAG retrieval (M5.2).

Cosine similarity + top-k selection over already-loaded candidate vectors. Kept
pure and I/O-free (like the routing engine) so the retrieval store can query a
tenant's chunks and this module ranks them — trivially unit-testable, and the
seam a pgvector/ANN index would replace at scale.
"""

import math
from collections.abc import Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return the cosine similarity of two vectors (0.0 for a zero/empty vector).

    Mismatched lengths yield ``0.0`` rather than raising, so a stray vector from a
    different embedding model degrades to "not similar" instead of breaking a
    best-effort retrieval.
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def top_k_indices(
    query: Sequence[float],
    candidates: Sequence[Sequence[float]],
    *,
    k: int,
    min_score: float = 0.0,
) -> list[tuple[int, float]]:
    """Rank ``candidates`` against ``query`` and return the best ``(index, score)``.

    Results are sorted by descending score, limited to ``k``, and filtered to
    scores strictly greater than ``min_score`` (so irrelevant chunks are dropped).
    Ties keep the earlier candidate (stable by original index).
    """
    if k <= 0:
        return []
    scored = [(i, cosine_similarity(query, candidate)) for i, candidate in enumerate(candidates)]
    relevant = [pair for pair in scored if pair[1] > min_score]
    relevant.sort(key=lambda pair: (-pair[1], pair[0]))
    return relevant[:k]
