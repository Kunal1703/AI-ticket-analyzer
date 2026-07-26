"""
Pydantic models for AI Ticket Analyzer.

Defines strongly-typed request/response schemas, enums for category and
priority, and OpenAI structured output schema.
"""

from enum import Enum

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TicketCategory(str, Enum):
    """Supported ticket categories for classification."""

    BILLING = "Billing"
    TECHNICAL_ISSUE = "Technical Issue"
    ACCOUNT_ACCESS = "Account Access"
    BUG_REPORT = "Bug Report"
    FEATURE_REQUEST = "Feature Request"
    SUBSCRIPTION = "Subscription"
    REFUND = "Refund"
    GENERAL_INQUIRY = "General Inquiry"


class TicketPriority(str, Enum):
    """Priority levels for support tickets."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class TicketStatus(str, Enum):
    """Lifecycle state of a ticket (M3.6).

    Transitions are unrestricted (any state to any state, including reopen); the
    value is stored as a string on ``tickets.status``.
    """

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketSort(str, Enum):
    """Sort order for the tickets list (M3.6)."""

    CREATED_DESC = "-created_at"  # newest first (default)
    CREATED_ASC = "created_at"  # oldest first


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------


class TicketRequest(BaseModel):
    """Incoming request payload for ticket analysis.

    Attributes:
        ticket: Raw customer support ticket text to analyze.
    """

    ticket: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Customer support ticket text to analyze.",
        json_schema_extra={
            "examples": [
                "I upgraded yesterday but my account still shows the free plan. "
                "I have already been charged twice."
            ]
        },
    )


class TicketAnalysis(BaseModel):
    """Structured analysis result returned by the AI.

    This model doubles as the OpenAI structured-output schema and the
    API response body.

    Attributes:
        summary: Concise summary of the customer's issue.
        category: Classified ticket category.
        priority: Assessed priority level.
        next_actions: Ordered list of recommended next steps.
    """

    summary: str = Field(
        ...,
        description="A concise one-to-two sentence summary of the ticket.",
    )
    category: TicketCategory = Field(
        ...,
        description="The most appropriate category for this ticket.",
    )
    priority: TicketPriority = Field(
        ...,
        description="The priority level based on urgency and impact.",
    )
    next_actions: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Ordered list of suggested next actions for the support agent.",
    )


class AnalyzeResponse(TicketAnalysis):
    """Analysis result plus the id of the associated ticket (M3.6).

    Returned by the tenant-scoped ``POST /v1/analyze`` and
    ``POST /v1/tickets/{id}/reanalyze`` so the caller can deep-link to the ticket.
    ``ticket_id`` is ``None`` only when no database is configured. The legacy
    public ``/analyze`` keeps returning a plain ``TicketAnalysis``.
    """

    ticket_id: str | None = Field(
        default=None,
        description="Id of the persisted ticket, or null when no database is configured.",
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str


class ReadyResponse(BaseModel):
    """Readiness check response with per-dependency statuses."""

    status: str  # "ready" | "not_ready"
    checks: dict[str, str]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    """Local registration payload."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    """Local login payload."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """Refresh-token exchange payload."""

    refresh_token: str


class TokenResponse(BaseModel):
    """Issued access + refresh tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Public representation of a user."""

    id: str
    email: str
    name: str | None = None
    is_verified: bool


# ---------------------------------------------------------------------------
# Tenancy (organizations & API keys)
# ---------------------------------------------------------------------------


class CreateOrgRequest(BaseModel):
    """Create-organization payload."""

    name: str = Field(..., min_length=1, max_length=255)


class OrgResponse(BaseModel):
    """Public representation of an organization."""

    id: str
    name: str
    slug: str
    plan: str


class CreateApiKeyRequest(BaseModel):
    """Create-API-key payload."""

    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["analyze"])


class ApiKeyResponse(BaseModel):
    """API key metadata (never includes the secret)."""

    id: str
    name: str
    prefix: str
    scopes: list[str]
    revoked: bool


class ApiKeyCreatedResponse(ApiKeyResponse):
    """API key metadata plus the one-time plaintext secret."""

    api_key: str


class TenantContextResponse(BaseModel):
    """The resolved tenant context for the current request."""

    organization_id: str
    principal_type: str
    scopes: list[str]


# ---------------------------------------------------------------------------
# Billing / usage
# ---------------------------------------------------------------------------


class UsageResponse(BaseModel):
    """An organization's current-period usage against its plan limit."""

    plan: str
    used: int
    limit: int | None  # None = unlimited
    period_start: str


class WebhookAck(BaseModel):
    """Acknowledgement returned to the billing provider for a webhook."""

    status: str


# ---------------------------------------------------------------------------
# Tickets (read / history)
# ---------------------------------------------------------------------------


class AnalysisRead(BaseModel):
    """One versioned analysis of a ticket (read model)."""

    id: str
    summary: str
    category: str
    priority: str
    next_actions: list[str]
    model: str | None = None
    prompt_version: str | None = None
    created_at: str


class TicketSummary(BaseModel):
    """A ticket list item: metadata plus its latest analysis (if any)."""

    id: str
    source: str
    status: str
    created_at: str
    analyses_count: int
    latest_category: str | None = None
    latest_priority: str | None = None
    latest_summary: str | None = None
    assignee: str | None = None
    sla_due_at: str | None = None


class TicketDetail(BaseModel):
    """A ticket with its full (versioned) analysis history."""

    id: str
    source: str
    status: str
    raw_text: str
    created_at: str
    assignee: str | None = None
    sla_due_at: str | None = None
    analyses: list[AnalysisRead]


class UpdateTicketRequest(BaseModel):
    """Partial update of a ticket's workspace fields (M3.6).

    Both fields are optional; only those *present in the request* are applied
    (detected via ``model_fields_set``), so ``{"assignee": null}`` clears the
    assignee while omitting it leaves it unchanged. At least one field is required.
    """

    status: TicketStatus | None = None
    assignee: str | None = Field(default=None, max_length=255)


class PaginatedTickets(BaseModel):
    """A page of tickets plus pagination metadata."""

    items: list[TicketSummary]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackRating(str, Enum):
    """Coarse human rating of an analysis."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class CreateFeedbackRequest(BaseModel):
    """Payload to record feedback on a ticket's analysis.

    ``analysis_id`` is optional: when omitted, the feedback attaches to the
    ticket's latest analysis. ``corrected_*`` capture the human's correction.
    """

    rating: FeedbackRating
    corrected_category: TicketCategory | None = None
    corrected_priority: TicketPriority | None = None
    comment: str | None = Field(default=None, max_length=2000)
    analysis_id: str | None = None


class FeedbackResponse(BaseModel):
    """A recorded piece of feedback."""

    id: str
    ticket_id: str
    analysis_id: str
    rating: str
    corrected_category: str | None = None
    corrected_priority: str | None = None
    comment: str | None = None
    created_at: str


# ---------------------------------------------------------------------------
# Batch analyze (async jobs)
# ---------------------------------------------------------------------------


class BatchRequest(BaseModel):
    """Payload to submit multiple tickets for asynchronous analysis."""

    tickets: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Between 1 and 50 ticket texts to analyze.",
    )

    @field_validator("tickets")
    @classmethod
    def _validate_items(cls, value: list[str]) -> list[str]:
        for text in value:
            length = len(text.strip())
            if length < 1 or length > 5000:
                raise ValueError("each ticket must be 1 to 5000 characters")
        return value


class BatchJobResponse(BaseModel):
    """Status of an asynchronous batch-analyze job."""

    id: str
    status: str
    total: int
    completed: int
    failed: int
    created_at: str


# ---------------------------------------------------------------------------
# Inbound channels
# ---------------------------------------------------------------------------


class EmailInboundRequest(BaseModel):
    """An inbound email to turn into a ticket and analyze."""

    from_address: str = Field(..., min_length=1, max_length=320)
    subject: str = Field(default="", max_length=1000)
    body: str = Field(..., min_length=1, max_length=10000)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class TimeseriesMetric(str, Enum):
    """Which entity a time series counts."""

    TICKETS = "tickets"
    ANALYSES = "analyses"


class AnalyticsSummary(BaseModel):
    """Aggregate metrics for an organization over an optional date window."""

    start: str | None = None
    end: str | None = None
    total_tickets: int
    total_analyses: int
    by_category: dict[str, int]
    by_priority: dict[str, int]


class TimeseriesPoint(BaseModel):
    """One day's count in a time series."""

    date: str
    count: int


class TimeseriesResponse(BaseModel):
    """A daily time series of tickets or analyses."""

    metric: str
    start: str | None = None
    end: str | None = None
    points: list[TimeseriesPoint]


# ---------------------------------------------------------------------------
# Knowledge base (RAG)
# ---------------------------------------------------------------------------


class CreateDocumentRequest(BaseModel):
    """Add a knowledge-base document for retrieval-augmented analysis."""

    title: str = Field(..., min_length=1, max_length=512)
    content: str = Field(..., min_length=1, max_length=100_000)
    source: str = Field(default="manual", min_length=1, max_length=32)


class DocumentSummary(BaseModel):
    """A knowledge-base document list item (no content)."""

    id: str
    title: str
    source: str
    created_at: str


class DocumentDetail(DocumentSummary):
    """A knowledge-base document with its content and chunk count."""

    content: str
    chunk_count: int


class DocumentCreatedResponse(DocumentSummary):
    """A newly ingested document plus how many chunks were embedded/stored."""

    chunk_count: int


class PaginatedDocuments(BaseModel):
    """A page of knowledge-base documents plus pagination metadata."""

    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class RetrievedChunkResponse(BaseModel):
    """One retrieved knowledge-base chunk and its similarity score."""

    document_id: str
    content: str
    score: float


class RetrievalResponse(BaseModel):
    """The result of a knowledge-base retrieval query."""

    query: str
    results: list[RetrievedChunkResponse]


# ---------------------------------------------------------------------------
# Resolution actions & audit (agentic actions — M5.3)
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    """Types of resolution action an agent can propose/execute on a ticket."""

    SET_STATUS = "set_status"  # internal: change the ticket status
    ASSIGN = "assign"  # internal: set the ticket assignee
    ADD_NOTE = "add_note"  # internal: record an internal note (audited)
    SEND_REPLY = "send_reply"  # outward: reply to the customer (destructive)
    ESCALATE = "escalate"  # outward: escalate the ticket (destructive)


class ActionStatus(str, Enum):
    """Lifecycle of a resolution action (enforced state machine, M5.3)."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class ActorType(str, Enum):
    """Who performed an audited event."""

    USER = "user"
    SYSTEM = "system"
    AI = "ai"


class SuggestedAction(BaseModel):
    """A single action a suggester proposes (also the LLM structured-output unit).

    Concrete optional fields (rather than a free-form dict) keep this compatible
    with LLM structured outputs; the service maps the set fields into the stored
    ``params`` JSONB per action type.
    """

    action_type: ActionType
    rationale: str = Field(..., min_length=1, max_length=1000)
    status: TicketStatus | None = None  # for set_status
    assignee: str | None = Field(default=None, max_length=255)  # for assign
    note: str | None = Field(default=None, max_length=5000)  # for add_note / reply body


class ResolutionPlan(BaseModel):
    """An ordered set of proposed actions (LLM structured-output schema, M5.3)."""

    actions: list[SuggestedAction] = Field(default_factory=list, max_length=10)


class ResolutionActionResponse(BaseModel):
    """A persisted resolution action."""

    id: str
    ticket_id: str
    analysis_id: str | None = None
    action_type: str
    params: dict[str, object]
    rationale: str | None = None
    status: str
    is_destructive: bool
    suggested_by: str | None = None
    approved_by: str | None = None
    result: dict[str, object] | None = None
    created_at: str


class SuggestActionsResponse(BaseModel):
    """The set of actions a suggest call proposed for a ticket."""

    ticket_id: str
    actions: list[ResolutionActionResponse]


class AuditLogResponse(BaseModel):
    """One append-only audit-log entry."""

    id: str
    actor_type: str
    actor_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict[str, object] | None = None
    created_at: str


# ---------------------------------------------------------------------------
# Outbound webhooks
# ---------------------------------------------------------------------------


class CreateWebhookRequest(BaseModel):
    """Register an outbound webhook endpoint."""

    url: HttpUrl
    event_types: list[str] = Field(
        default_factory=lambda: ["batch.completed"],
        min_length=1,
        max_length=20,
        description="Event types this endpoint subscribes to.",
    )


class WebhookResponse(BaseModel):
    """A registered webhook (never includes the signing secret)."""

    id: str
    url: str
    event_types: list[str]
    active: bool


class WebhookCreatedResponse(WebhookResponse):
    """A newly created webhook plus its one-time signing secret."""

    secret: str


# ---------------------------------------------------------------------------
# Routing & SLA
# ---------------------------------------------------------------------------


class RoutingConditions(BaseModel):
    """Match conditions for a routing rule (present keys must all match)."""

    category: str | None = None
    priority: str | None = None


class RoutingActions(BaseModel):
    """Actions applied when a routing rule matches."""

    assignee: str | None = None
    tags: list[str] = Field(default_factory=list)


class CreateRoutingRuleRequest(BaseModel):
    """Create a routing rule."""

    name: str = Field(..., min_length=1, max_length=255)
    position: int = Field(default=0, ge=0)
    conditions: RoutingConditions = Field(default_factory=RoutingConditions)
    actions: RoutingActions = Field(default_factory=RoutingActions)


class RoutingRuleResponse(BaseModel):
    """A registered routing rule."""

    id: str
    name: str
    position: int
    conditions: dict[str, str]
    actions: dict[str, object]
    active: bool


class CreateSlaPolicyRequest(BaseModel):
    """Create an SLA policy (a resolution deadline for a priority)."""

    priority: str = Field(..., min_length=1, max_length=32)
    resolution_minutes: int = Field(..., ge=1)


class SlaPolicyResponse(BaseModel):
    """A registered SLA policy."""

    id: str
    priority: str
    resolution_minutes: int
    active: bool


class RoutingResult(BaseModel):
    """The outcome of routing a ticket (also persisted on the ticket)."""

    assignee: str | None = None
    tags: list[str]
    matched_rule_id: str | None = None
    sla_due_at: str | None = None
