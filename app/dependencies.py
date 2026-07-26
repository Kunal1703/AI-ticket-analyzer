"""
FastAPI dependency providers for AI Ticket Analyzer.

Shared resources (settings, cache, AI provider) are created once by the
application factory and stored on ``app.state``. These dependencies expose them
to endpoints via ``Depends``, which also makes them trivially overridable in
tests through ``app.dependency_overrides``.
"""

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.actions.base import ActionStore, ActionSuggester, AuditStore
from app.actions.handlers import build_action_handlers
from app.actions.service import ActionService
from app.actions.suggester import build_action_suggester
from app.ai.base import AnalysisProvider
from app.analytics.base import AnalyticsStore
from app.analytics.service import AnalyticsService
from app.auth.base import AuthError, UserStore
from app.auth.service import AuthService
from app.auth.tokens import TokenError, TokenService
from app.billing.base import QuotaExceededError, UsageStore, WebhookEventStore
from app.billing.plans import Plan
from app.billing.provider import BillingProvider
from app.billing.service import BillingService, WebhookService
from app.cache import Cache
from app.config import Settings
from app.db.action_store import SqlAlchemyActionStore, SqlAlchemyAuditStore
from app.db.analytics_store import SqlAlchemyAnalyticsStore
from app.db.api_key_store import SqlAlchemyApiKeyStore
from app.db.batch_job_store import SqlAlchemyBatchJobStore
from app.db.feedback_store import SqlAlchemyFeedbackStore
from app.db.models import Membership, User
from app.db.org_store import SqlAlchemyOrgStore
from app.db.routing_store import SqlAlchemyRoutingRuleStore, SqlAlchemySlaPolicyStore
from app.db.ticket_store import SqlAlchemyTicketStore
from app.db.usage_store import SqlAlchemyUsageStore
from app.db.user_store import SqlAlchemyUserStore
from app.db.vector_store import SqlAlchemyVectorStore
from app.db.webhook_delivery_store import SqlAlchemyWebhookDeliveryStore
from app.db.webhook_event_store import SqlAlchemyWebhookEventStore
from app.db.webhook_store import SqlAlchemyWebhookStore
from app.embeddings.base import EmbeddingProvider
from app.jobs.base import BatchJobStore, JobRunner
from app.jobs.service import BatchService
from app.observability import metrics
from app.rag.base import VectorStore
from app.rag.retrieval import ContextRetriever, build_context_retriever
from app.rag.service import RagService
from app.routing.base import RoutingRuleStore, SlaPolicyStore
from app.tenancy.base import (
    ApiKeyStore,
    ForbiddenError,
    OrgStore,
    TenantContext,
    TenantError,
)
from app.tenancy.service import ApiKeyService, OrganizationService
from app.tickets.base import FeedbackStore, TicketStore
from app.webhooks.base import WebhookDispatcher, WebhookStore
from app.webhooks.dispatcher import HttpWebhookDispatcher, NoOpWebhookDispatcher


def get_app_settings(request: Request) -> Settings:
    """Return the settings bound to the running application."""
    settings: Settings = request.app.state.settings
    return settings


def get_analysis_provider(request: Request) -> AnalysisProvider:
    """Return the AI provider bound to the running application."""
    provider: AnalysisProvider = request.app.state.provider
    return provider


def get_cache(request: Request) -> Cache:
    """Return the response cache bound to the running application."""
    cache: Cache = request.app.state.cache
    return cache


def get_db_sessionmaker(
    request: Request,
) -> async_sessionmaker[AsyncSession] | None:
    """Return the async session factory, or ``None`` if persistence is disabled."""
    sessionmaker: async_sessionmaker[AsyncSession] | None = request.app.state.db_sessionmaker
    return sessionmaker


# ---------------------------------------------------------------------------
# Authentication dependencies
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_session(
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped DB session, committing on success.

    Returns 503 when no database is configured (authentication requires one).
    """
    if sessionmaker is None:
        raise HTTPException(status_code=503, detail="Database is not configured.")
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_token_service(request: Request) -> TokenService:
    """Return the token service, or 503 if authentication is not configured."""
    token_service: TokenService | None = request.app.state.token_service
    if token_service is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    return token_service


def get_user_store(session: AsyncSession = Depends(get_db_session)) -> UserStore:
    """Return a user store bound to the request session."""
    return SqlAlchemyUserStore(session)


def get_auth_service(
    request: Request,
    user_store: UserStore = Depends(get_user_store),
    token_service: TokenService = Depends(get_token_service),
) -> AuthService:
    """Assemble the provider-agnostic auth service for this request."""
    return AuthService(user_store, token_service, request.app.state.settings)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """Resolve the authenticated user from a Bearer access token."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return await auth_service.get_current_user(credentials.credentials)
    except (AuthError, TokenError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


# ---------------------------------------------------------------------------
# Tenancy dependencies
# ---------------------------------------------------------------------------


def get_optional_token_service(request: Request) -> TokenService | None:
    """Return the token service, or None (no 503) — for optional-auth paths."""
    token_service: TokenService | None = request.app.state.token_service
    return token_service


def get_org_store(session: AsyncSession = Depends(get_db_session)) -> OrgStore:
    """Return an organization store bound to the request session."""
    return SqlAlchemyOrgStore(session)


def get_api_key_store(session: AsyncSession = Depends(get_db_session)) -> ApiKeyStore:
    """Return an API-key store bound to the request session."""
    return SqlAlchemyApiKeyStore(session)


def get_org_service(org_store: OrgStore = Depends(get_org_store)) -> OrganizationService:
    return OrganizationService(org_store)


def get_api_key_service(
    api_key_store: ApiKeyStore = Depends(get_api_key_store),
) -> ApiKeyService:
    return ApiKeyService(api_key_store)


async def require_org_membership(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
) -> Membership:
    """Ensure the current user is a member of ``org_id`` (path param); else 403."""
    try:
        return await org_service.require_membership(org_id, current_user.id)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail="Not a member of this organization") from exc


async def get_tenant_context(
    request: Request,
    api_key_service: ApiKeyService = Depends(get_api_key_service),
    org_store: OrgStore = Depends(get_org_store),
    user_store: UserStore = Depends(get_user_store),
    token_service: TokenService | None = Depends(get_optional_token_service),
    settings: Settings = Depends(get_app_settings),
) -> TenantContext:
    """Resolve the tenant context from an API key (``X-API-Key``) or a user JWT.

    API-key resolution does not require ``JWT_SECRET``; the JWT path is used only
    when an ``Authorization: Bearer`` token is present and auth is configured.
    """
    api_key_value = request.headers.get("X-API-Key")
    if api_key_value:
        try:
            key = await api_key_service.authenticate(api_key_value)
        except TenantError as exc:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key") from exc
        return TenantContext(
            organization_id=key.organization_id,
            principal_type="api_key",
            api_key_id=key.id,
            scopes=tuple(key.scopes or ()),
        )

    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer ") and token_service is not None:
        token = authorization.split(" ", 1)[1]
        auth_service = AuthService(user_store, token_service, settings)
        try:
            user = await auth_service.get_current_user(token)
        except (AuthError, TokenError) as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        return await _tenant_context_for_user(request, user, org_store)

    raise HTTPException(status_code=401, detail="Not authenticated")


async def _tenant_context_for_user(
    request: Request, user: User, org_store: OrgStore
) -> TenantContext:
    orgs = await org_store.list_for_user(user.id)
    if not orgs:
        raise HTTPException(status_code=403, detail="User has no organization")

    header_org = request.headers.get("X-Organization-Id")
    if header_org:
        try:
            target = uuid.UUID(header_org)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid X-Organization-Id") from exc
        if await org_store.get_membership(target, user.id) is None:
            raise HTTPException(status_code=403, detail="Not a member of this organization")
        return TenantContext(organization_id=target, principal_type="user", user_id=user.id)

    if len(orgs) == 1:
        return TenantContext(organization_id=orgs[0].id, principal_type="user", user_id=user.id)
    raise HTTPException(status_code=400, detail="Multiple organizations; set X-Organization-Id")


# ---------------------------------------------------------------------------
# Authorization (RBAC roles + API-key scopes)
# ---------------------------------------------------------------------------


def require_role(*allowed_roles: str) -> Callable[..., Awaitable[Membership]]:
    """Dependency factory: require the current user's membership role to be allowed.

    Layered on ``require_org_membership`` (which reads ``org_id`` from the path),
    so it also enforces membership. Returns the ``Membership`` for downstream use.
    """
    allowed = frozenset(allowed_roles)

    async def _dependency(
        membership: Membership = Depends(require_org_membership),
    ) -> Membership:
        if membership.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient role for this action")
        return membership

    return _dependency


def require_scope(*required_scopes: str) -> Callable[..., Awaitable[TenantContext]]:
    """Dependency factory: require the resolved tenant context to hold the scopes.

    Scopes are only enforced for **API-key** principals (machine callers); user
    principals are governed by roles instead. Returns the ``TenantContext``.
    """
    required = frozenset(required_scopes)

    async def _dependency(
        context: TenantContext = Depends(get_tenant_context),
    ) -> TenantContext:
        if context.principal_type == "api_key" and not required.issubset(context.scopes):
            raise HTTPException(status_code=403, detail="Insufficient API key scope")
        return context

    return _dependency


# ---------------------------------------------------------------------------
# Billing / usage quotas
# ---------------------------------------------------------------------------

# Module-level singleton for the scope-checked context feeding quota enforcement.
_require_analyze_scope = require_scope("analyze")


def get_usage_store(session: AsyncSession = Depends(get_db_session)) -> UsageStore:
    """Return a usage store bound to the request session."""
    return SqlAlchemyUsageStore(session)


def get_billing_service(
    request: Request,
    usage_store: UsageStore = Depends(get_usage_store),
) -> BillingService:
    """Assemble the billing service with the application's plan registry."""
    plans: dict[str, Plan] = request.app.state.plans
    return BillingService(usage_store, plans)


async def require_quota(
    context: TenantContext = Depends(_require_analyze_scope),
    org_store: OrgStore = Depends(get_org_store),
    billing: BillingService = Depends(get_billing_service),
) -> TenantContext:
    """Enforce the org's monthly analysis quota; 402 when the plan limit is reached.

    Layered on ``require_scope("analyze")`` so it also enforces authentication and
    the API-key scope, then reads the org's plan and checks usage. Returns the
    ``TenantContext`` for the endpoint.
    """
    org = await org_store.get(context.organization_id)
    plan_name = org.plan if org is not None else None
    try:
        await billing.check_quota(context.organization_id, plan_name)
    except QuotaExceededError as exc:
        metrics.record_quota_denied("analysis")
        raise HTTPException(
            status_code=402,
            detail="Monthly analysis quota reached for your plan.",
        ) from exc
    return context


def get_billing_provider(request: Request) -> BillingProvider:
    """Return the configured billing provider, or 503 if billing is not configured."""
    provider: BillingProvider | None = request.app.state.billing_provider
    if provider is None:
        raise HTTPException(status_code=503, detail="Billing is not configured.")
    return provider


def get_webhook_event_store(
    session: AsyncSession = Depends(get_db_session),
) -> WebhookEventStore:
    """Return a processed-webhook-event store bound to the request session."""
    return SqlAlchemyWebhookEventStore(session)


def get_webhook_service(
    provider: BillingProvider = Depends(get_billing_provider),
    event_store: WebhookEventStore = Depends(get_webhook_event_store),
    org_store: OrgStore = Depends(get_org_store),
) -> WebhookService:
    """Assemble the webhook ingestion service for this request."""
    return WebhookService(provider, event_store, org_store)


# ---------------------------------------------------------------------------
# Tickets (read)
# ---------------------------------------------------------------------------


def get_ticket_store(session: AsyncSession = Depends(get_db_session)) -> TicketStore:
    """Return a tenant-scoped ticket read store bound to the request session."""
    return SqlAlchemyTicketStore(session)


def get_feedback_store(session: AsyncSession = Depends(get_db_session)) -> FeedbackStore:
    """Return a tenant-scoped feedback store bound to the request session."""
    return SqlAlchemyFeedbackStore(session)


# ---------------------------------------------------------------------------
# Routing & SLA
# ---------------------------------------------------------------------------


def get_routing_rule_store(session: AsyncSession = Depends(get_db_session)) -> RoutingRuleStore:
    """Return a routing-rule store bound to the request session."""
    return SqlAlchemyRoutingRuleStore(session)


def get_sla_policy_store(session: AsyncSession = Depends(get_db_session)) -> SlaPolicyStore:
    """Return an SLA-policy store bound to the request session."""
    return SqlAlchemySlaPolicyStore(session)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def get_analytics_store(session: AsyncSession = Depends(get_db_session)) -> AnalyticsStore:
    """Return an analytics store bound to the request session."""
    return SqlAlchemyAnalyticsStore(session)


# ---------------------------------------------------------------------------
# RAG (knowledge base + retrieval)
# ---------------------------------------------------------------------------


def get_vector_store(session: AsyncSession = Depends(get_db_session)) -> VectorStore:
    """Return a tenant-scoped vector/KB store bound to the request session."""
    return SqlAlchemyVectorStore(session)


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    """Return the embedding provider, or 503 if RAG is not configured.

    Built once by the application factory; ``None`` when the embedding provider
    could not be constructed (e.g. missing key), so RAG endpoints degrade to 503
    like other optional subsystems.
    """
    provider: EmbeddingProvider | None = request.app.state.embedding_provider
    if provider is None:
        raise HTTPException(status_code=503, detail="Embeddings are not configured.")
    return provider


def get_rag_service(
    settings: Settings = Depends(get_app_settings),
    vector_store: VectorStore = Depends(get_vector_store),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> RagService:
    """Assemble the RAG service (ingestion + retrieval) for this request.

    Requires embeddings (503 if unconfigured); read-only listing/deletion of
    documents use ``get_vector_store`` directly and work without embeddings.
    """
    return RagService(
        vector_store,
        embedding_provider,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        top_k=settings.rag_top_k,
        max_candidates=settings.rag_max_candidates,
        min_score=settings.rag_min_score,
    )


def get_context_retriever(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    sessionmaker: async_sessionmaker[AsyncSession] | None = Depends(get_db_sessionmaker),
) -> ContextRetriever | None:
    """Return the best-effort RAG retriever for the analyze path, or ``None``.

    ``None`` when RAG is disabled, no database is configured, or no embedding
    provider was built — the analyze path then behaves exactly as before.
    """
    embedding_provider: EmbeddingProvider | None = request.app.state.embedding_provider
    return build_context_retriever(
        sessionmaker=sessionmaker,
        embedding_provider=embedding_provider,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Agentic resolution actions (M5.3)
# ---------------------------------------------------------------------------


def get_action_store(session: AsyncSession = Depends(get_db_session)) -> ActionStore:
    """Return a tenant-scoped resolution-action store bound to the request session."""
    return SqlAlchemyActionStore(session)


def get_audit_store(session: AsyncSession = Depends(get_db_session)) -> AuditStore:
    """Return a tenant-scoped audit-log store bound to the request session."""
    return SqlAlchemyAuditStore(session)


def get_action_suggester(
    request: Request, settings: Settings = Depends(get_app_settings)
) -> ActionSuggester:
    """Return the configured action suggester (rule-based default, or LLM)."""
    provider: AnalysisProvider = request.app.state.provider
    return build_action_suggester(settings, provider=provider)


def get_action_service(
    action_store: ActionStore = Depends(get_action_store),
    audit_store: AuditStore = Depends(get_audit_store),
    suggester: ActionSuggester = Depends(get_action_suggester),
) -> ActionService:
    """Assemble the action service (suggest/approve/execute + audit) for this request."""
    return ActionService(action_store, audit_store, suggester, build_action_handlers())


async def require_approver(
    context: TenantContext = Depends(get_tenant_context),
    org_store: OrgStore = Depends(get_org_store),
) -> TenantContext:
    """Require a privileged **human** to approve/execute actions.

    Approvals must come from a **user** (never an API key — machines can't
    approve their own actions) who is an ``owner``/``admin`` of the org. Returns
    the context (its ``user_id`` is the approver, recorded in the audit log).
    """
    if context.principal_type != "user" or context.user_id is None:
        raise HTTPException(status_code=403, detail="Action approval requires a user")
    membership = await org_store.get_membership(context.organization_id, context.user_id)
    if membership is None or membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Owner or admin required for this action")
    return context


def get_analytics_service(
    store: AnalyticsStore = Depends(get_analytics_store),
) -> AnalyticsService:
    """Assemble the analytics service for this request."""
    return AnalyticsService(store)


# ---------------------------------------------------------------------------
# Async jobs / batch analyze
# ---------------------------------------------------------------------------


def get_job_runner(request: Request) -> JobRunner:
    """Return the job runner bound to the running application."""
    runner: JobRunner = request.app.state.job_runner
    return runner


def get_batch_job_store(request: Request) -> BatchJobStore:
    """Return a batch-job store, or 503 if persistence is disabled.

    Batch jobs must be durable (visible to the background task), so the store is
    backed by the application's sessionmaker rather than a request session.
    """
    sessionmaker: async_sessionmaker[AsyncSession] | None = request.app.state.db_sessionmaker
    if sessionmaker is None:
        raise HTTPException(status_code=503, detail="Batch analysis requires a database.")
    return SqlAlchemyBatchJobStore(sessionmaker)


def get_batch_service(
    job_store: BatchJobStore = Depends(get_batch_job_store),
    runner: JobRunner = Depends(get_job_runner),
) -> BatchService:
    """Assemble the batch-analyze service for this request."""
    return BatchService(job_store, runner)


# ---------------------------------------------------------------------------
# Outbound webhooks
# ---------------------------------------------------------------------------


def get_webhook_store(request: Request) -> WebhookStore:
    """Return a webhook registration store, or 503 if persistence is disabled."""
    sessionmaker: async_sessionmaker[AsyncSession] | None = request.app.state.db_sessionmaker
    if sessionmaker is None:
        raise HTTPException(status_code=503, detail="Webhooks require a database.")
    return SqlAlchemyWebhookStore(sessionmaker)


def get_webhook_dispatcher(request: Request) -> WebhookDispatcher:
    """Return the webhook dispatcher.

    When no database is configured, returns a no-op dispatcher so callers (e.g. the
    batch path) work without webhooks; delivery is a background, best-effort concern.
    """
    sessionmaker: async_sessionmaker[AsyncSession] | None = request.app.state.db_sessionmaker
    if sessionmaker is None:
        return NoOpWebhookDispatcher()
    settings: Settings = request.app.state.settings
    return HttpWebhookDispatcher(
        SqlAlchemyWebhookStore(sessionmaker),
        SqlAlchemyWebhookDeliveryStore(sessionmaker),
        request.app.state.http_client,
        max_attempts=settings.webhook_max_attempts,
        timeout_seconds=settings.webhook_timeout_seconds,
    )
