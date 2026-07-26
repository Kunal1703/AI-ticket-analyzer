# 20 — Inbound Channels

Implemented in **M3.5**. Files: `app/channels/{__init__,csv_parser,routes}.py`,
`app/jobs/submit.py` (shared batch-submit helper), `EmailInboundRequest` model,
`source` threaded through `run_analysis`/`persist_analysis`. **No migration** (reuses
`tickets`/`analyses`/`batch_jobs` and the existing `tickets.source` column).

## What M3.5 does

Ingest tickets from non-API sources into the existing analyze pipeline, tenant-scoped
and metered + quota-gated (like `/v1/analyze`), reusing `run_analysis` (and, for CSV,
the M3.3a batch pipeline) — no analyze logic is duplicated:

| Method | Path | Source | Purpose |
|---|---|---|---|
| POST | `/v1/channels/email` | `email` | Turn an email into a ticket + analyze it (returns the analysis) |
| POST | `/v1/channels/import` | `csv` | Parse a CSV upload → submit rows as an async batch (202 + job) |

## Source threading

`run_analysis(..., source="api")` → `persist_analysis(..., source=…)` →
`get_or_create_ticket(source=…)` (which already accepted `source`). Default `"api"`
preserves all existing behavior; email/CSV ingestion tags tickets `"email"`/`"csv"`
for provenance (queryable via `/v1/tickets`). Dedupe is unchanged (by
`text_hash`+org); `source` is set when the ticket row is first created.

## Email channel (`POST /v1/channels/email`)

An **authenticated tenant endpoint** (`require_quota` → tenant context, metered +
quota-gated). Body `{from_address, subject, body}` is combined into the ticket text
(`"{subject}\n\n{body}"`) and analyzed via `run_analysis(source="email")`; returns a
`TicketAnalysis` (same shape as `/v1/analyze`). The mail-provider **inbound webhook**
(a per-org inbound address/token + signature, so a provider like Mailgun/SendGrid can
POST unauthenticated) is a documented follow-up — it needs a live provider to verify
and a small addressing table.

## CSV import (`POST /v1/channels/import`)

The CSV is the **raw request body** (`text/csv`) — no `python-multipart` dependency.
`app/channels/csv_parser.py::parse_csv_tickets` decodes UTF-8 (BOM-tolerant), picks a
column named (case-insensitively) `text`/`ticket`/`body`/`message`/`description` — or
the single column — extracts non-empty rows, and raises `ValueError` (→ **400**) on
malformed / empty / >`MAX_IMPORT_ROWS` (50) input. The rows are submitted as an async
batch (`source="csv"`); a `batch.completed` webhook fires on completion for free.

## Shared batch-submit helper (`app/jobs/submit.py`)

`submit_analyze_batch(..., source=…)` builds the per-item `analyze_one` (reusing
`run_analysis`) and the `on_complete` `batch.completed` dispatch, then submits — so
**both** the `/v1/analyze/batch` route and the CSV import channel share one
orchestration (parameterized by `source`). `batch_job_response` renders the job.

## What must NEVER change

- Channels reuse `run_analysis`/the batch pipeline (no second analyze path); ingested
  tickets are tagged with their `source`.
- Both channel endpoints stay tenant-scoped + metered + quota-gated.
- CSV import stays dependency-light (raw body, stdlib `csv`); parse failures are 400.

## Deferred / next

- **Mail-provider inbound webhook**: per-org inbound address/token + signature
  verification + org resolution (unauthenticated provider callback).
- Richer email parsing (attachments, threading/dedupe by Message-ID), more import
  formats, and returning created ticket ids from the email channel.
