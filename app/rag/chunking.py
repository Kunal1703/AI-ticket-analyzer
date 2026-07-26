"""
Pure text chunking for RAG ingestion (M5.2).

Splits a document into overlapping, word-bounded chunks so each chunk is small
enough to embed meaningfully while overlap preserves context across boundaries.
No I/O — trivially unit-testable (mirrors the pure routing engine).
"""

DEFAULT_CHUNK_SIZE = 200
DEFAULT_CHUNK_OVERLAP = 40


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split ``text`` into overlapping chunks of at most ``chunk_size`` words.

    Args:
        text: The document text to split.
        chunk_size: Maximum number of words per chunk (must be > 0).
        overlap: Number of words each chunk shares with the previous one; clamped
            to ``[0, chunk_size - 1]`` so progress is always made.

    Returns:
        A list of chunk strings (empty when ``text`` has no words).
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    words = text.split()
    if not words:
        return []

    step = chunk_size - max(0, min(overlap, chunk_size - 1))
    chunks: list[str] = []
    start = 0
    while start < len(words):
        chunk_words = words[start : start + chunk_size]
        chunks.append(" ".join(chunk_words))
        if start + chunk_size >= len(words):
            break
        start += step
    return chunks
