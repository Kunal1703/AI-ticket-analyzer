"""
Prometheus metrics for AI Ticket Analyzer.

Metrics are module-level singletons (registered once against the default
registry). Helper functions wrap label usage so callers stay decoupled from the
metric objects.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# --- HTTP ---
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
)

# --- Analysis / cache / LLM ---
analyses_total = Counter(
    "ticket_analyses_total",
    "Ticket analyses performed via a provider.",
    ["provider", "outcome"],
)
cache_requests_total = Counter(
    "cache_requests_total",
    "Cache lookups by result.",
    ["result"],
)
llm_tokens_total = Counter(
    "llm_tokens_total",
    "LLM tokens consumed.",
    ["provider", "type"],
)

# --- Billing / usage ---
usage_events_total = Counter(
    "usage_events_total",
    "Metered usage events recorded for billing.",
    ["event_type"],
)
quota_denied_total = Counter(
    "quota_denied_total",
    "Requests rejected because a plan quota was reached.",
    ["event_type"],
)
billing_webhooks_total = Counter(
    "billing_webhooks_total",
    "Billing webhook events received by outcome.",
    ["provider", "outcome"],
)

# --- Async jobs ---
batch_jobs_total = Counter(
    "batch_jobs_total",
    "Batch-analyze jobs by final status.",
    ["status"],
)
webhook_deliveries_total = Counter(
    "webhook_deliveries_total",
    "Outbound webhook deliveries by final status.",
    ["status"],
)

# --- RAG ---
rag_retrievals_total = Counter(
    "rag_retrievals_total",
    "Knowledge-base retrievals on the analyze path by outcome.",
    ["outcome"],
)


def record_http_request(method: str, path: str, status: int, duration_seconds: float) -> None:
    """Record one HTTP request's count and duration."""
    http_requests_total.labels(method=method, path=path, status=str(status)).inc()
    http_request_duration_seconds.labels(method=method, path=path).observe(duration_seconds)


def record_analysis(provider: str, outcome: str) -> None:
    """Record a provider analysis outcome ("success" or "error")."""
    analyses_total.labels(provider=provider, outcome=outcome).inc()


def record_cache(result: str) -> None:
    """Record a cache lookup result ("hit" or "miss")."""
    cache_requests_total.labels(result=result).inc()


def record_tokens(provider: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Record prompt/completion token usage for a provider."""
    if prompt_tokens:
        llm_tokens_total.labels(provider=provider, type="prompt").inc(prompt_tokens)
    if completion_tokens:
        llm_tokens_total.labels(provider=provider, type="completion").inc(completion_tokens)


def record_usage_event(event_type: str, quantity: int = 1) -> None:
    """Record one metered usage event."""
    usage_events_total.labels(event_type=event_type).inc(quantity)


def record_quota_denied(event_type: str) -> None:
    """Record a request rejected due to a plan quota."""
    quota_denied_total.labels(event_type=event_type).inc()


def record_billing_webhook(provider: str, outcome: str) -> None:
    """Record a billing webhook outcome (e.g. processed/duplicate/ignored/invalid)."""
    billing_webhooks_total.labels(provider=provider, outcome=outcome).inc()


def record_batch_job(status: str) -> None:
    """Record a batch job reaching a final status."""
    batch_jobs_total.labels(status=status).inc()


def record_webhook_delivery(status: str) -> None:
    """Record an outbound webhook delivery outcome (delivered/failed)."""
    webhook_deliveries_total.labels(status=status).inc()


def record_rag_retrieval(outcome: str) -> None:
    """Record a KB retrieval on the analyze path (grounded/empty/error)."""
    rag_retrievals_total.labels(outcome=outcome).inc()


def render() -> tuple[bytes, str]:
    """Return the metrics exposition payload and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
