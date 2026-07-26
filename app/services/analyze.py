"""
Shared analysis orchestration.

Both the legacy public ``/analyze`` (organization_id=None) and the tenant-scoped
``/v1/analyze`` (organization_id set) call ``run_analysis``. Keeping the cache /
provider / metrics / persistence flow in one place avoids divergence between the
two endpoints.

``run_analysis`` lets ``Provider*`` exceptions propagate — they are mapped to
HTTP responses by a single exception handler (see ``app.core.errors``), so both
endpoints get identical error behavior for free.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AnalysisProvider, ProviderError
from app.billing.metering import record_analysis_usage
from app.cache.base import Cache, cache_key
from app.models import TicketAnalysis
from app.observability import metrics
from app.services.analysis_service import persist_analysis, resolve_ticket_id

# (organization_id, query) -> grounding context, or None. Best-effort: the
# retriever swallows its own errors (see app.rag.retrieval), so run_analysis can
# call it without a guard — a failure simply yields no context.
ContextRetriever = Callable[[uuid.UUID, str], Awaitable[str | None]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyzeOutcome:
    """Result of ``run_analysis``: the analysis plus the associated ticket id.

    ``ticket_id`` is the id of the persisted (or, on a cache hit, the existing)
    ticket, or ``None`` when no database is configured. It is surfaced by the
    tenant-scoped endpoints so callers can deep-link to the ticket, while the
    cached/returned ``analysis`` stays a plain ``TicketAnalysis``.
    """

    analysis: TicketAnalysis
    ticket_id: uuid.UUID | None = None


async def run_analysis(
    *,
    ticket_text: str,
    provider: AnalysisProvider,
    cache: Cache,
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    organization_id: uuid.UUID | None = None,
    bypass_cache: bool = False,
    source: str = "api",
    retrieve_context: ContextRetriever | None = None,
) -> AnalyzeOutcome:
    """Analyze a ticket with cache, metrics, and best-effort persistence.

    The content hash is used for the DB dedupe key; the cache key is additionally
    namespaced by organization so tenants never share cached analyses.

    ``bypass_cache=True`` forces a fresh provider call (used by re-analyze): the
    cache read is skipped, a new versioned analysis is appended under the existing
    ticket, and the cache is still refreshed with the new result.

    ``retrieve_context`` (RAG, M5.2) is an optional best-effort retriever; when
    provided on the tenant path it grounds the analysis in the org's knowledge
    base. Retrieved context is folded into the cache key (so grounded and
    ungrounded results never collide) and passed to the provider. It is only used
    for the tenant-scoped path (``organization_id`` set); the legacy path is
    unchanged.
    """
    logger.info(
        "Analyzing ticket (length=%d chars, org=%s, bypass_cache=%s)",
        len(ticket_text),
        organization_id,
        bypass_cache,
    )

    content_hash = cache_key(ticket_text)
    ck = content_hash if organization_id is None else f"{organization_id}:{content_hash}"

    # Best-effort RAG grounding (tenant path only). The retriever never raises.
    context: str | None = None
    if retrieve_context is not None and organization_id is not None:
        context = await retrieve_context(organization_id, ticket_text)
        if context:
            ck = f"{ck}:rag:{cache_key(context)}"

    if not bypass_cache:
        cached = await cache.get(ck)
        if cached is not None:
            logger.info("Cache hit for ticket")
            metrics.record_cache("hit")
            # Nothing is persisted on a hit, but the tenant path still wants the
            # ticket id to deep-link to. Resolve it best-effort (skip the DB for
            # the legacy org-less path, which never uses it).
            ticket_id = (
                await resolve_ticket_id(
                    sessionmaker, text_hash=content_hash, organization_id=organization_id
                )
                if organization_id is not None
                else None
            )
            return AnalyzeOutcome(analysis=cached, ticket_id=ticket_id)
        metrics.record_cache("miss")

    try:
        result = await provider.analyze(ticket_text, context=context)
    except ProviderError:
        metrics.record_analysis(provider.name, "error")
        raise  # mapped to HTTP by the provider exception handler

    analysis = result.analysis
    metrics.record_analysis(provider.name, "success")
    if result.usage is not None:
        metrics.record_tokens(
            provider.name, result.usage.prompt_tokens, result.usage.completion_tokens
        )

    await cache.set(ck, analysis)
    # Best-effort persistence: no-op without a DB, never breaks the response.
    ticket_id = await persist_analysis(
        sessionmaker,
        ticket_text=ticket_text,
        text_hash=content_hash,
        analysis=analysis,
        model=provider.model,
        usage=result.usage,
        prompt_version=result.prompt_version,
        organization_id=organization_id,
        source=source,
    )
    # Best-effort usage metering: no-op for the legacy path (organization_id=None)
    # or without a DB; never breaks the response. Only real analyses (cache misses)
    # are metered, matching how tokens are counted.
    await record_analysis_usage(
        sessionmaker,
        organization_id=organization_id,
        model=provider.model,
        total_tokens=result.usage.total_tokens if result.usage is not None else None,
    )
    return AnalyzeOutcome(analysis=analysis, ticket_id=ticket_id)
