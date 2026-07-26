"""
FastAPI application for AI Ticket Analyzer.

Provides an application factory (:func:`create_app`) that wires configuration,
shared resources (response cache and AI provider), middleware, error handling,
and routes. A module-level ``app`` instance is exposed for ``uvicorn
app.main:app``.
"""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.actions.routes import router as actions_router
from app.ai import AnalysisProvider, ProviderError, build_provider
from app.analytics.routes import router as analytics_router
from app.auth.routes import router as auth_router
from app.auth.tokens import TokenService
from app.billing.plans import build_plans
from app.billing.provider import build_billing_provider
from app.billing.routes import router as billing_router
from app.cache import Cache, build_cache
from app.channels.routes import router as channels_router
from app.config import Settings, get_settings
from app.core.errors import (
    http_exception_handler,
    provider_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.db.session import create_db_engine, create_sessionmaker
from app.dependencies import (
    get_analysis_provider,
    get_app_settings,
    get_cache,
    get_context_retriever,
    get_db_sessionmaker,
    require_quota,
)
from app.embeddings import EmbeddingProvider, build_embedding_provider
from app.jobs.base import JobRunner
from app.jobs.routes import router as batch_router
from app.jobs.runner import build_job_runner
from app.models import (
    AnalyzeResponse,
    HealthResponse,
    ReadyResponse,
    TicketAnalysis,
    TicketRequest,
)
from app.observability import metrics
from app.rag.retrieval import ContextRetriever
from app.rag.routes import router as rag_router
from app.readiness import check_readiness
from app.routing.routes import router as routing_router
from app.services.analyze import run_analysis
from app.tenancy.base import TenantContext
from app.tenancy.routes import router as tenancy_router
from app.tickets.routes import router as tickets_router
from app.webhooks.routes import router as webhooks_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    """Expose Prometheus metrics."""
    payload, content_type = metrics.render()
    return Response(content=payload, media_type=content_type)


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Health check",
    description="Returns service health status and version.",
)
async def health_check(
    settings: Settings = Depends(get_app_settings),
) -> HealthResponse:
    """Lightweight liveness probe — does not check dependencies."""
    return HealthResponse(version=settings.app_version)


@router.get(
    "/ready",
    response_model=ReadyResponse,
    tags=["System"],
    summary="Readiness check",
    description=(
        "Reports whether the service's dependencies (database, cache) are "
        "reachable. Returns 503 when not ready. Does not call the AI provider."
    ),
)
async def readiness_check(
    response: Response,
    cache: Cache = Depends(get_cache),
    provider: AnalysisProvider = Depends(get_analysis_provider),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
) -> ReadyResponse:
    """Readiness probe for orchestrators/load balancers."""
    ready, checks = await check_readiness(sessionmaker, cache, provider)
    if not ready:
        response.status_code = 503
    return ReadyResponse(status="ready" if ready else "not_ready", checks=checks)


@router.post(
    "/analyze",
    response_model=TicketAnalysis,
    tags=["Analysis"],
    summary="Analyze a support ticket",
    description=(
        "Accepts a customer support ticket and returns an AI-generated "
        "analysis including summary, category, priority, and suggested "
        "next actions."
    ),
    responses={
        200: {
            "description": "Successful analysis",
            "content": {
                "application/json": {
                    "example": {
                        "summary": (
                            "Customer upgraded but account remains on free plan "
                            "and was charged twice."
                        ),
                        "category": "Billing",
                        "priority": "High",
                        "next_actions": [
                            "Verify payment records",
                            "Check account subscription status",
                            "Issue refund if duplicate charge confirmed",
                        ],
                    }
                }
            },
        },
        422: {"description": "Validation error (e.g. empty ticket)"},
        429: {"description": "AI provider rate limit exceeded"},
        502: {"description": "AI provider failure or invalid response"},
        504: {"description": "AI provider timeout"},
    },
)
async def analyze(
    payload: TicketRequest,
    provider: AnalysisProvider = Depends(get_analysis_provider),
    cache: Cache = Depends(get_cache),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
) -> TicketAnalysis:
    """Analyze a customer support ticket using AI (legacy, unauthenticated).

    Kept for backward compatibility. Not tenant-scoped (organization_id is NULL).
    New integrations should use ``POST /v1/analyze``.
    """
    outcome = await run_analysis(
        ticket_text=payload.ticket.strip(),
        provider=provider,
        cache=cache,
        sessionmaker=sessionmaker,
        organization_id=None,
    )
    return outcome.analysis


@router.post(
    "/v1/analyze",
    response_model=AnalyzeResponse,
    tags=["Analysis"],
    summary="Analyze a support ticket (tenant-scoped)",
    description=(
        "Authenticated, tenant-scoped analysis. Resolve the tenant via a user "
        "JWT (Authorization: Bearer) or an API key (X-API-Key). API-key callers "
        "must hold the 'analyze' scope. The analysis is persisted under the "
        "resolved organization."
    ),
    responses={
        401: {"description": "Not authenticated"},
        402: {"description": "Monthly analysis quota reached for the plan"},
        403: {"description": "Insufficient scope / not a member"},
        429: {"description": "AI provider rate limit exceeded"},
        502: {"description": "AI provider failure or invalid response"},
        503: {"description": "Tenancy requires a database"},
        504: {"description": "AI provider timeout"},
    },
)
async def analyze_v1(
    payload: TicketRequest,
    context: TenantContext = Depends(require_quota),
    provider: AnalysisProvider = Depends(get_analysis_provider),
    cache: Cache = Depends(get_cache),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
    retrieve_context: ContextRetriever | None = Depends(get_context_retriever),
) -> AnalyzeResponse:
    """Analyze a ticket scoped to the caller's organization."""
    outcome = await run_analysis(
        ticket_text=payload.ticket.strip(),
        provider=provider,
        cache=cache,
        sessionmaker=sessionmaker,
        organization_id=context.organization_id,
        retrieve_context=retrieve_context,
    )
    return AnalyzeResponse(
        **outcome.analysis.model_dump(),
        ticket_id=str(outcome.ticket_id) if outcome.ticket_id is not None else None,
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


async def request_timing_middleware(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
    """Measure request time; add X-Process-Time header; record HTTP metrics."""
    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_s = time.perf_counter() - start
    response.headers["X-Process-Time-Ms"] = f"{duration_s * 1000:.2f}"

    # Use the matched route template as the metric label to bound cardinality.
    route = request.scope.get("route")
    path = getattr(route, "path", "other")
    metrics.record_http_request(request.method, path, response.status_code, duration_s)

    logger.info(
        "%s %s — %d (%.0f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_s * 1000,
    )
    return response


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler — startup/shutdown and resource cleanup."""
    settings: Settings = application.state.settings
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    yield
    runner: JobRunner = application.state.job_runner
    await runner.aclose()
    http_client: httpx.AsyncClient = application.state.http_client
    await http_client.aclose()
    embedding_provider: EmbeddingProvider | None = application.state.embedding_provider
    if embedding_provider is not None:
        await embedding_provider.aclose()
    provider: AnalysisProvider = application.state.provider
    await provider.aclose()
    cache: Cache = application.state.cache
    await cache.aclose()
    engine: AsyncEngine | None = application.state.db_engine
    if engine is not None:
        await engine.dispose()
    logger.info("Shutting down %s", settings.app_name)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure a FastAPI application.

    Shared resources (response cache and AI provider) are created here and
    stored on ``app.state``, then exposed to routes via ``app.dependencies``.
    This makes resource lifecycle explicit and dependencies overridable in
    tests.

    Args:
        settings: Optional settings override (defaults to global settings).

    Returns:
        A configured ``FastAPI`` instance.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered customer support ticket analyzer. "
            "Classifies tickets by category and priority, generates summaries, "
            "and suggests next actions using AI structured outputs."
        ),
        lifespan=lifespan,
    )

    # Shared resources, owned by the application.
    application.state.settings = settings
    application.state.cache = build_cache(settings)
    application.state.provider = build_provider(settings)
    # Plan registry for billing/usage quotas (placeholder limits, configurable).
    application.state.plans = build_plans(settings.plan_monthly_analysis_limits)

    # Async job runner for batch analyze (in-process by default; no infra needed).
    application.state.job_runner = build_job_runner(settings)

    # Shared HTTP client for outbound webhook delivery.
    application.state.http_client = httpx.AsyncClient()

    # Optional embeddings provider for RAG (M5.2). Built defensively: if it can't
    # be constructed (e.g. missing key), RAG endpoints degrade to 503 and the
    # analyze path simply retrieves no context — the app still boots.
    application.state.embedding_provider = None
    try:
        application.state.embedding_provider = build_embedding_provider(settings)
        logger.info("Embeddings enabled (%s)", settings.embedding_provider)
    except ValueError as exc:
        logger.info("Embeddings disabled: %s", exc)

    # Optional billing provider: only wired when a webhook secret is configured.
    application.state.billing_provider = None
    if settings.stripe_webhook_secret:
        application.state.billing_provider = build_billing_provider(settings)
        logger.info("Billing webhooks enabled (%s)", settings.billing_provider)

    # Optional persistence: only wired when a database URL is configured.
    application.state.db_engine = None
    application.state.db_sessionmaker = None
    if settings.database_url:
        engine = create_db_engine(settings.database_url)
        application.state.db_engine = engine
        application.state.db_sessionmaker = create_sessionmaker(engine)
        logger.info("Database persistence enabled")

    # Optional authentication: only wired when a JWT secret is configured.
    application.state.token_service = None
    if settings.jwt_secret:
        application.state.token_service = TokenService(
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
            access_ttl_seconds=settings.access_token_ttl_seconds,
            refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
        )
        logger.info("Authentication enabled")

    # CORS — origins are configurable; never combine a wildcard origin with
    # credentials (browsers reject it and it is insecure).
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(SecurityHeadersMiddleware)
    # Timing is registered before RequestContext so that RequestContext is the
    # outermost middleware: it sets the request-id contextvar before the timing
    # middleware's access log runs, so that log line is correlated too.
    application.middleware("http")(request_timing_middleware)
    application.add_middleware(RequestContextMiddleware)

    # Standardized error envelope for all error responses (status codes preserved).
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    application.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    application.add_exception_handler(ProviderError, provider_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)

    application.include_router(router)
    application.include_router(auth_router)
    application.include_router(tenancy_router)
    application.include_router(billing_router)
    application.include_router(tickets_router)
    application.include_router(batch_router)
    application.include_router(webhooks_router)
    application.include_router(routing_router)
    application.include_router(channels_router)
    application.include_router(analytics_router)
    application.include_router(rag_router)
    application.include_router(actions_router)
    return application


app = create_app()
