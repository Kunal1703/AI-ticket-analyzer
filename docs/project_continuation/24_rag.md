# 24 — RAG over the Knowledge Base (M5.2)

The second **Phase 5 (AI moat)** milestone. Grounds tenant-scoped analyses in an
organization's **knowledge base** via retrieval-augmented generation: documents
are chunked, embedded through a **provider-agnostic embeddings layer**, stored in
a **tenant-isolated vector store** behind a port, and the nearest chunks are fed
as context into `run_analysis`. Everything is opt-in, best-effort on the analyze
path, and eval-gated by the M5.1 harness.

Files: `app/embeddings/*` (embeddings abstraction), `app/rag/*` (chunking,
similarity, vector-store port, service, retrieval, routes), `app/db/vector_store.py`
(`SqlAlchemyVectorStore`), `documents` + `document_chunks` ORM + migration `0012`,
`app/prompts.py` (context-aware `v2`), the additive `context` parameter on
`AnalysisProvider.analyze`, and wiring in `app/services/analyze.py`,
`app/dependencies.py`, `app/main.py`, `app/tickets/routes.py`. Design decision:
**D33**.

## Why

M5.1 made prompts versioned and measurable; M5.2 makes analyses **grounded**. A
support org's real triage quality depends on *its* policies, runbooks, and past
resolutions — knowledge the base model doesn't have. RAG retrieves the relevant
excerpts per ticket and lets the LLM cite them, improving summary/next-action
specificity without fine-tuning. It is the substrate M5.3 (auto-resolve) builds on.

## The embeddings abstraction (`app/embeddings/`)

A sibling of the AI provider layer (D3), same shape:

```
EmbeddingProvider (ABC): name, model, embed(texts) -> list[vector], embed_one, aclose
Embedding{Timeout,RateLimit,Connection,Response}Error  ⊂ EmbeddingError
EmbeddingConfig (neutral value object)                 # like ProviderConfig
_EMBEDDING_PROVIDERS registry + build_embedding_provider(settings)
```

- **`OpenAIEmbeddingProvider`** serves OpenAI **and any OpenAI-compatible**
  embeddings endpoint (Ollama, custom gateway) via `base_url`; lazy client,
  tenacity retries, and translation of SDK errors into `Embedding*` — exactly
  mirroring `OpenAIProvider`.
- **`HashEmbeddingProvider`** (`hash`) is a **keyless, deterministic** feature-
  hashing embedder (uses a stable `blake2b` hash, not Python's salted `hash()`).
  It needs no API key and no network, so RAG runs **fully offline** — for local
  dev and the default test suite — mirroring the in-memory cache / in-process job
  runner. It is *not* semantically meaningful; production uses a real model.
- **Selection:** `EMBEDDING_PROVIDER` (default `openai`) + `EMBEDDING_*` settings.
  The API key **falls back to `llm_api_key`** (embeddings usually share the LLM
  account), so whatever boots the app also enables embeddings.
- **Registry-ready:** a different embeddings API (e.g. Cohere) is a new
  `EmbeddingProvider` + one `_EMBEDDING_PROVIDERS` entry — no RAG/business change.

The provider is built **defensively** in `create_app` → `app.state.embedding_provider`
(and disposed in `lifespan`): if it can't be constructed (e.g. `openai` without a
key while using a keyless LLM), it is `None` and RAG endpoints return **503** —
the app still boots. This matches the optional-subsystem pattern (billing/auth).

## The knowledge base schema (migration `0012`)

Two tenant-scoped tables (see [03_database.md](03_database.md)):

- **`documents`** — `organization_id` (NOT NULL, FK cascade, indexed), `title`,
  `content` (source of truth), `source` (`manual`/`ticket`), `created_at`.
- **`document_chunks`** — `organization_id` (NOT NULL, **denormalized** like
  `analyses.organization_id` so similarity search filters by tenant without a
  join), `document_id` (FK cascade, indexed), `chunk_index`, `content`, and
  **`embedding` (JSONB list[float])**, `created_at`.

**Why JSONB, not pgvector:** it needs no extra dependency or Postgres extension,
is offline-verifiable (`alembic upgrade head --sql`), provider/dimension-agnostic,
and keeps ranking testable in pure Python. A **pgvector/ANN index is the deferred
scale optimization** (the same "OLAP deferred" reasoning as analytics, D29) — the
`VectorStore.search` seam already isolates where it would land.

## Pure helpers (I/O-free, unit-tested)

Mirroring the pure routing engine (D27):

- **`app/rag/chunking.py::chunk_text`** — word-bounded overlapping chunks
  (`rag_chunk_size`/`rag_chunk_overlap`); overlap is clamped below the chunk size
  so progress is always made, and no redundant tiny trailing chunk is emitted.
- **`app/rag/similarity.py`** — `cosine_similarity` (0.0 on zero/empty/mismatched
  vectors, so a stray vector from a different model degrades to "not similar"
  instead of raising) and `top_k_indices` (rank desc, filter `> min_score`, cap
  at `k`, stable ties).

## The vector store (port + impl)

- **`VectorStore`** port (`app/rag/base.py`, tenant-scoped throughout):
  `create_document`, `add_chunks`, `list_documents`, `count_documents`,
  `get_document`, `count_chunks`, `delete_document`, and
  `list_chunks_for_org(org, *, limit)` (retrieval candidates, capped by
  `rag_max_candidates` — the scale guard). Ranking is deliberately **not** on the
  port: the store loads a tenant's candidates, the pure similarity helpers rank
  them ("store loads rows, pure engine evaluates", like routing).
- **`SqlAlchemyVectorStore`** (`app/db/vector_store.py`) takes a provided
  `AsyncSession`, so it works with either a **request-scoped** session (KB
  management routes) or a **self-contained** session opened from the sessionmaker
  (best-effort retrieval on the analyze path). `PreparedChunk` carries an index +
  content + embedding.

## The RAG service (`app/rag/service.py`)

`RagService` (store + embedding-provider injected; HTTP-free, fake-testable):

- **`ingest`** — chunk → embed → store. A deliberate management action: embedding
  failures **propagate** (the route maps them to 502).
- **`retrieve`** — embed the query, load the org's candidates, rank with the pure
  helpers, return `RetrievedChunk`s (document id + content + score). Always scoped
  to one org (a blank query returns `[]`).

## Knowledge-base endpoints (`app/rag/routes.py`, prefix `/v1`)

| Method | Path | Guard | Purpose |
|---|---|---|---|
| POST | `/orgs/{org_id}/documents` | owner/admin | Ingest a document (chunk+embed); returns `chunk_count`. 502 on embed failure |
| GET | `/orgs/{org_id}/documents` | membership | Paginated list |
| GET | `/orgs/{org_id}/documents/search?q=&k=` | membership | Retrieve ranked chunks for a query |
| GET | `/orgs/{org_id}/documents/{id}` | membership | Detail (content + chunk_count); 404 cross-org |
| DELETE | `/orgs/{org_id}/documents/{id}` | owner/admin | Delete (204/404) |

Management mirrors routing/webhook config (owner/admin to write, membership to
read). The `/search` route is declared **before** `/{document_id}` so `search`
isn't parsed as a UUID. Writes need embeddings (503 if unconfigured); list/read/
delete use the vector store directly and work without embeddings.

## Grounding the analyze path

- **Prompt `v2`** (`app/prompts.py`) is a **new, append-only** version with a
  `context_prompt_builder` that folds retrieved excerpts into the user message and
  a system prompt instructing the model to use them when relevant (and never
  fabricate). **`v1` is unchanged** and ignores context (its `context_prompt_builder`
  is `None`) — so historical/no-RAG behavior is byte-identical. Enable grounding
  with `RAG_ENABLED=true` **and** `LLM_PROMPT_VERSION=v2`.
- **`AnalysisProvider.analyze(ticket_text, *, context=None)`** — additive optional
  kwarg. `None` reproduces prior behavior; the `TicketAnalysis` contract and
  `Provider*` translation are unchanged. The provider folds `context` in via the
  selected `PromptVersion.build_user_message`.
- **`run_analysis(..., retrieve_context=None)`** — on the **tenant path only**
  (`organization_id` set), it calls the best-effort retriever, folds any returned
  context into the **cache key** (`{org}:{hash}:rag:{ctx_hash}`, so grounded and
  ungrounded results never collide), and passes it to the provider. The legacy
  org-less `/analyze` never retrieves.
- **`build_context_retriever`** (`app/rag/retrieval.py`) returns the retriever, or
  `None` when RAG is disabled / no DB / no embeddings (then the analyze path is
  identical to before). The retriever is **best-effort**: it opens its own session
  (like `persist_analysis`/`resolve_ticket_id`), swallows every error, and returns
  `None` — a broken/empty KB or a down embedding provider degrades to an ungrounded
  analysis and never breaks the response. `get_context_retriever` injects it into
  `/v1/analyze` and `/v1/tickets/{id}/reanalyze`.
- **Metric:** `rag_retrievals_total{outcome}` (`grounded`/`empty`/`error`).

## Configuration

`EMBEDDING_PROVIDER`/`EMBEDDING_MODEL`/`EMBEDDING_API_KEY`/`EMBEDDING_BASE_URL`/
`EMBEDDING_TIMEOUT`/`EMBEDDING_MAX_RETRIES`/`EMBEDDING_DIMENSIONS` (hash only);
`RAG_ENABLED` (opt-in grounding, default off), `RAG_TOP_K`, `RAG_MAX_CANDIDATES`,
`RAG_MIN_SCORE`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`. All have safe defaults.

## Testing (all offline)

- `tests/test_embeddings.py` — hash provider (determinism, normalization,
  lexical-overlap ranking), OpenAI provider (success + each `Embedding*`
  translation via a mocked client), factory (defaults, key fallback, validation).
- `tests/test_rag_core.py` — pure chunking + similarity + schema registration.
- `tests/test_rag_store.py` — `SqlAlchemyVectorStore` mocked-session units + a
  `skipif` DB round-trip (create/list/count/delete + cross-org isolation).
- `tests/test_rag.py` — `RagService` (ingest/retrieve, tenant-scoped) + KB routes
  (CRUD, search ranking, 502 on embed failure, 422, 404) via a `FakeVectorStore` +
  the hash embedder; DI wiring (503/assembly).
- `tests/test_rag_analyze.py` — prompt `v1`/`v2`, `run_analysis` retrieval
  (context→provider, cache-key namespacing, legacy path skipped, empty context),
  `build_context_retriever` (enabled/disabled + grounded/empty/best-effort), and
  `/v1/analyze` grounded end-to-end.
- Migration `0012` verified offline (`alembic upgrade head --sql`).

## What must NEVER change (D33)

- Every vector is **tenant-scoped** by `organization_id` (documents, chunks,
  retrieval) — RAG must never leak one org's knowledge into another's analysis.
- The embeddings layer stays **provider-agnostic** (SDK behind the port, errors
  translated to `Embedding*`) with a **keyless offline default** (`hash`); the app
  boots even when the embedding provider can't be built (RAG → 503).
- Analyze-path retrieval stays **best-effort** (own session, swallows errors,
  degrades to no context) and **tenant-only** (never on the legacy `/analyze`).
- Prompt `v2` is **append-only** and `v1` stays context-free (D32); `analyze`'s
  `context` kwarg is additive — the `TicketAnalysis` contract and `Provider*`
  translation are unchanged.
- Retrieved context is folded into the cache key so grounded/ungrounded results
  never collide.

## Deferred / next

- **pgvector/ANN** vector index for scale (JSONB + Python ranking is fine at
  current scale); caching embeddings; hybrid lexical+vector retrieval.
- Grounding the **batch** and **channel** paths (they reuse `run_analysis`, so it
  is a small extension — pass a retriever there too).
- Indexing **past resolved tickets** as a document source (`source="ticket"`);
  citations surfaced in the API/frontend; a frontend KB management UI.
- **M5.3 — auto-resolve + agentic actions** (human-approved, audited), built on
  this grounding and the M5.1 eval harness.
