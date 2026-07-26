"""
CSV parsing for the import channel.

Extracts ticket texts from an uploaded CSV. A column named (case-insensitively)
one of ``text``/``ticket``/``body``/``message``/``description`` is used; if the
file has a single column, that column is used. Raises ``ValueError`` (mapped to
HTTP 400 by the route) on malformed / empty / oversized input.
"""

import csv
import io

# Kept in sync with the batch endpoint's per-request limit.
MAX_IMPORT_ROWS = 50

_TEXT_COLUMNS = ("text", "ticket", "body", "message", "description")


def _pick_column(fieldnames: list[str]) -> str | None:
    named = [f for f in fieldnames if f]
    lower = {f.lower(): f for f in named}
    for candidate in _TEXT_COLUMNS:
        if candidate in lower:
            return lower[candidate]
    return named[0] if len(named) == 1 else None


def parse_csv_tickets(content: bytes) -> list[str]:
    """Return the non-empty ticket texts from a CSV upload.

    Raises:
        ValueError: The file is not UTF-8, has no usable header/column, contains
            no ticket rows, or exceeds ``MAX_IMPORT_ROWS``.
    """
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("file must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise ValueError("CSV is empty or missing a header row")

    column = _pick_column(list(reader.fieldnames))
    if column is None:
        raise ValueError("no text column found (expected one of: " + ", ".join(_TEXT_COLUMNS) + ")")

    texts: list[str] = []
    for row in reader:
        value = (row.get(column) or "").strip()
        if value:
            texts.append(value)

    if not texts:
        raise ValueError("no ticket rows found")
    if len(texts) > MAX_IMPORT_ROWS:
        raise ValueError(f"too many rows (max {MAX_IMPORT_ROWS})")
    return texts
