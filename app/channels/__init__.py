"""
Inbound channels (Milestone M3.5).

Ingest tickets from non-API sources into the existing analyze pipeline:

- **Email** (``POST /v1/channels/email``): an authenticated tenant endpoint that
  turns an email (from/subject/body) into a ticket and analyzes it (source
  ``"email"``).
- **CSV import** (``POST /v1/channels/import``): parses an uploaded CSV of ticket
  texts and submits them as an async batch (source ``"csv"``), reusing the M3.3a
  batch pipeline.

Both are tenant-scoped, metered + quota-gated, and reuse ``run_analysis`` — no
analyze logic is duplicated. The mail-provider inbound webhook (per-org address /
token + signature) is a documented follow-up.
"""

from app.channels.csv_parser import MAX_IMPORT_ROWS, parse_csv_tickets

__all__ = ["MAX_IMPORT_ROWS", "parse_csv_tickets"]
