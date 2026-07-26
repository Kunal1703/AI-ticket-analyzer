"""
Configuration module for AI Ticket Analyzer.

Manages environment variables and application settings using Pydantic's
BaseSettings for automatic environment variable loading and validation.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    The LLM configuration is provider-agnostic. ``OPENAI_*`` environment names
    are still accepted as backward-compatible aliases for the generic ``LLM_*``
    settings.

    Attributes:
        app_name: Display name of the application.
        app_version: Current application version string.
        debug: When true, forces the logging level to DEBUG (overrides log_level).
        ai_provider: AI backend to use — one of the registered providers
            (e.g. "openai", "groq", "together", "openrouter", "ollama",
            "openai-compatible"). Selects the concrete provider via
            app.ai.factory.
        llm_api_key: API key/token for the selected provider. Optional — some
            providers (e.g. Ollama) need none. Alias: OPENAI_API_KEY.
        llm_model: Model identifier. When unset, the provider's default is used.
            Alias: OPENAI_MODEL.
        llm_base_url: API base URL for the provider. When unset, a per-provider
            default (or the SDK default for OpenAI) is used.
        llm_timeout: Maximum seconds to wait for a provider response.
            Alias: OPENAI_TIMEOUT.
        llm_max_retries: Maximum attempts for transient failures, including the
            first try. Alias: OPENAI_MAX_RETRIES.
        llm_temperature: Sampling temperature for the model.
        llm_prompt_version: Prompt version to use (see app.prompts); None uses
            the default. Recorded on each analysis for eval/traceability.
        embedding_provider: Embeddings backend for RAG (M5.2) — one of "openai",
            "ollama", "openai-compatible", or the keyless local "hash".
        embedding_model: Embedding model id; None uses the provider default.
        embedding_api_key: API key for the embeddings provider; falls back to
            llm_api_key when unset.
        embedding_base_url: Base URL for the embeddings provider (or the SDK/
            per-provider default).
        embedding_timeout: Maximum seconds to wait for an embeddings response.
        embedding_max_retries: Maximum attempts for transient embedding failures.
        embedding_dimensions: Output vector size for the keyless "hash" provider.
        rag_enabled: When true, the tenant-scoped analyze path retrieves KB
            context and grounds the analysis on it (best-effort). Off by default.
        rag_top_k: Number of chunks retrieved per analysis/search.
        rag_max_candidates: Max chunks loaded per org before ranking (scale guard).
        rag_min_score: Minimum cosine similarity for a chunk to be included.
        rag_chunk_size: Max words per document chunk at ingestion.
        rag_chunk_overlap: Words shared between consecutive chunks.
        action_suggester: Resolution-action suggester (M5.3) — "rule" (offline
            default) or "llm" (reuses the AI provider). Actions are always
            human-approved regardless.
        cache_ttl_seconds: Time-to-live (seconds) for cached ticket analyses;
            0 or negative disables caching.
        job_queue: Backend for async batch jobs — "background" (in-process,
            default) or a future Redis-backed worker.
        webhook_max_attempts: Max delivery attempts per outbound webhook (inline
            retries with backoff).
        webhook_timeout_seconds: Per-attempt HTTP timeout for outbound webhooks.
        log_level: Python logging level name (used when debug is false).
        log_format: Log output format — "json" (structured, default) or "text".
        cors_allow_origins: Browser origins permitted by CORS. Defaults to
            common local-development origins; set explicitly in production.
            Provide as a JSON array in the environment, e.g.
            ``CORS_ALLOW_ORIGINS=["https://app.example.com"]``.
        cors_allow_credentials: Whether to allow credentialed CORS requests
            (cookies/Authorization). Must not be combined with a wildcard
            origin; defaults to False as no cookie-based auth exists yet.
        database_url: Optional SQLAlchemy URL for persistence, e.g.
            ``postgresql+psycopg://user:pw@host:5432/db``. When unset, the
            application runs without a database.
        redis_url: Optional Redis URL for a shared cache, e.g.
            ``redis://localhost:6379/0``. When unset, an in-memory cache is used.
        plan_monthly_analysis_limits: Optional per-plan overrides for the monthly
            analysis quota (a ``None`` value means unlimited). Merged over the
            placeholder plan registry; unset means use the defaults.
        billing_provider: Name of the billing backend (currently "stripe").
        stripe_api_key: Stripe secret key (for future outbound API calls).
        stripe_webhook_secret: Signing secret used to verify inbound Stripe
            webhooks. When unset, the billing webhook endpoint returns 503.
        stripe_price_plan_map: Optional mapping of Stripe price id/lookup_key to a
            local plan slug, used to sync ``Organization.plan`` from webhooks.
        jwt_secret: Secret used to sign auth tokens. When unset, authentication
            endpoints are disabled (return 503).
        jwt_algorithm: JWT signing algorithm (default HS256).
        access_token_ttl_seconds: Access-token lifetime in seconds.
        refresh_token_ttl_seconds: Refresh-token lifetime in seconds.
    """

    app_name: str = "AI Ticket Analyzer"
    app_version: str = "1.0.0"
    debug: bool = False

    # AI provider selection (see app.ai for the provider abstraction).
    ai_provider: str = "openai"

    # Generic LLM configuration (provider-agnostic). OPENAI_* names are accepted
    # as backward-compatible aliases.
    llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("llm_api_key", "openai_api_key"),
    )
    llm_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("llm_model", "openai_model"),
    )
    llm_base_url: str | None = None
    llm_timeout: int = Field(
        default=30,
        validation_alias=AliasChoices("llm_timeout", "openai_timeout"),
    )
    # At least one attempt is required; 0 would never call the provider.
    llm_max_retries: int = Field(
        default=3,
        ge=1,
        validation_alias=AliasChoices("llm_max_retries", "openai_max_retries"),
    )
    llm_temperature: float = 0.2
    # Prompt version to use (see app.prompts). None -> the default version.
    # Recorded on each analysis (analyses.prompt_version) for eval/traceability.
    llm_prompt_version: str | None = None

    # Embeddings (RAG, M5.2). Provider-agnostic, mirroring the LLM settings.
    # "openai"/"ollama"/"openai-compatible" use the OpenAI SDK; "hash" is a
    # keyless deterministic local backend for dev/testing (no infra, no network).
    # The API key falls back to ``llm_api_key`` when ``embedding_api_key`` is
    # unset (embeddings usually share the LLM account).
    embedding_provider: str = "openai"
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_timeout: int = 30
    embedding_max_retries: int = Field(default=3, ge=1)
    # Output vector size for the keyless ``hash`` provider only (real models
    # determine the dimension themselves).
    embedding_dimensions: int = 256

    # RAG (M5.2). ``rag_enabled`` opts the analyze path into grounding on the
    # tenant's knowledge base (best-effort; off by default so behavior is
    # unchanged). The rest tune chunking + retrieval.
    rag_enabled: bool = False
    rag_top_k: int = Field(default=4, ge=1)
    rag_max_candidates: int = Field(default=500, ge=1)
    rag_min_score: float = 0.0
    rag_chunk_size: int = Field(default=200, ge=1)
    rag_chunk_overlap: int = Field(default=40, ge=0)

    # Agentic resolution actions (M5.3). The suggester that proposes actions —
    # "rule" (deterministic, offline default) or "llm" (reuses the AI provider).
    # Actions are always human-approved; this only selects who *proposes* them.
    action_suggester: str = "rule"

    # Caching
    cache_ttl_seconds: int = 300  # 5 minutes

    # Async jobs / batch analyze. The default "background" runner executes jobs
    # in-process (no infra); "arq" (a Redis-backed worker) is a future backend.
    job_queue: str = "background"

    # Outbound webhooks (M3.3b). Bounded inline retries per delivery.
    webhook_max_attempts: int = 3
    webhook_timeout_seconds: float = 10.0

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Database (optional; app runs without it)
    database_url: str | None = None

    # Cache (optional; falls back to in-memory when unset)
    redis_url: str | None = None

    # Billing / usage quotas. Optional per-plan overrides for the monthly analysis
    # limit (None value = unlimited); merged over the placeholder plan registry in
    # app.billing.plans. Provide as a JSON object in the environment, e.g.
    # ``PLAN_MONTHLY_ANALYSIS_LIMITS={"free": 50, "pro": 5000, "enterprise": null}``.
    plan_monthly_analysis_limits: dict[str, int | None] | None = None

    # Billing provider (Stripe). All optional; the webhook endpoint returns 503
    # until ``stripe_webhook_secret`` is set. ``stripe_price_plan_map`` maps a
    # Stripe price id or lookup_key to a local plan slug (JSON object), e.g.
    # ``STRIPE_PRICE_PLAN_MAP={"price_123": "pro", "biz_lookup": "enterprise"}``.
    billing_provider: str = "stripe"
    stripe_api_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_plan_map: dict[str, str] | None = None

    # Auth / JWT (optional; auth endpoints return 503 until jwt_secret is set)
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_seconds: int = 1_209_600  # 14 days

    # CORS
    cors_allow_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ]
    cors_allow_credentials: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings (singleton pattern)."""
    return Settings()
