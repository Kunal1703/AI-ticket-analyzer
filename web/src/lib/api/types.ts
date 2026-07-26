/**
 * TypeScript mirrors of the backend's Pydantic response/request schemas
 * (`app/models.py`). Kept intentionally narrow — only the fields the frontend
 * consumes — and hand-written rather than generated, since the surface is small
 * and this milestone (M4.2) is a scaffold. If the API surface grows, replace
 * this with generated types from the OpenAPI schema.
 */

/** `POST /v1/auth/{signup,login,refresh}` response. */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

/** `GET /v1/auth/me` response. */
export interface UserResponse {
  id: string;
  email: string;
  name: string | null;
  is_verified: boolean;
}

/** `GET /v1/orgs` item / `POST /v1/orgs` response. */
export interface OrgResponse {
  id: string;
  name: string;
  slug: string;
  plan: string;
}

/**
 * The backend's standardized error envelope
 * (`{"error": {code, message, request_id, details?}}`).
 */
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: unknown;
  };
}

// ---------------------------------------------------------------------------
// Tickets / analyses (M4.3) — mirrors app/models.py
// ---------------------------------------------------------------------------

/** The 8 fixed ticket categories (enum *values*, used verbatim as filters). */
export const TICKET_CATEGORIES = [
  "Billing",
  "Technical Issue",
  "Account Access",
  "Bug Report",
  "Feature Request",
  "Subscription",
  "Refund",
  "General Inquiry",
] as const;
export type TicketCategory = (typeof TICKET_CATEGORIES)[number];

/** The 4 priority levels. */
export const TICKET_PRIORITIES = ["Low", "Medium", "High", "Critical"] as const;
export type TicketPriority = (typeof TICKET_PRIORITIES)[number];

/** The ticket lifecycle states (M3.6), stored/queried as value strings. */
export const TICKET_STATUSES = ["open", "in_progress", "pending", "resolved", "closed"] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

/** Human labels for the (snake_case) status values. */
export const STATUS_LABELS: Record<TicketStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  pending: "Pending",
  resolved: "Resolved",
  closed: "Closed",
};

/** Known ingestion sources (for the list filter). */
export const TICKET_SOURCES = ["api", "email", "csv"] as const;

/** Sort orders for the tickets list. */
export const TICKET_SORTS = ["-created_at", "created_at"] as const;
export type TicketSort = (typeof TICKET_SORTS)[number];

/** Analysis payload shared by the analyze responses and versioned reads. */
export interface TicketAnalysis {
  summary: string;
  category: string;
  priority: string;
  next_actions: string[];
}

/** `POST /v1/analyze` and `.../reanalyze` response (analysis + ticket id). */
export interface AnalyzeResponse extends TicketAnalysis {
  ticket_id: string | null;
}

/** `PATCH /v1/tickets/{id}` request body (partial; only sent fields apply). */
export interface UpdateTicketBody {
  status?: TicketStatus;
  /** `null` clears the assignee; a string sets it; omit to leave unchanged. */
  assignee?: string | null;
}

/** One versioned analysis of a ticket. */
export interface AnalysisRead {
  id: string;
  summary: string;
  category: string;
  priority: string;
  next_actions: string[];
  model: string | null;
  created_at: string;
}

/** A ticket list item (metadata + its latest analysis). */
export interface TicketSummary {
  id: string;
  source: string;
  status: string;
  created_at: string;
  analyses_count: number;
  latest_category: string | null;
  latest_priority: string | null;
  latest_summary: string | null;
  assignee: string | null;
  sla_due_at: string | null;
}

/** A ticket with its full versioned analysis history. */
export interface TicketDetail {
  id: string;
  source: string;
  status: string;
  raw_text: string;
  created_at: string;
  assignee: string | null;
  sla_due_at: string | null;
  analyses: AnalysisRead[];
}

/** `GET /v1/tickets` response. */
export interface PaginatedTickets {
  items: TicketSummary[];
  total: number;
  limit: number;
  offset: number;
}

export type FeedbackRating = "positive" | "negative";

/** `POST /v1/tickets/{id}/feedback` request body. */
export interface CreateFeedbackBody {
  rating: FeedbackRating;
  corrected_category?: string | null;
  corrected_priority?: string | null;
  comment?: string | null;
  analysis_id?: string | null;
}

/** A recorded piece of feedback. */
export interface FeedbackResponse {
  id: string;
  ticket_id: string;
  analysis_id: string;
  rating: string;
  corrected_category: string | null;
  corrected_priority: string | null;
  comment: string | null;
  created_at: string;
}

/** `POST /v1/tickets/{id}/route` response. */
export interface RoutingResult {
  assignee: string | null;
  tags: string[];
  matched_rule_id: string | null;
  sla_due_at: string | null;
}

// ---------------------------------------------------------------------------
// Analytics (M4.4) — mirrors app/models.py
// ---------------------------------------------------------------------------

export type TimeseriesMetric = "tickets" | "analyses";

/** `GET /v1/analytics/summary` response. */
export interface AnalyticsSummary {
  start: string | null;
  end: string | null;
  total_tickets: number;
  total_analyses: number;
  by_category: Record<string, number>;
  by_priority: Record<string, number>;
}

/** One day's count in a time series. */
export interface TimeseriesPoint {
  date: string;
  count: number;
}

/** `GET /v1/analytics/timeseries` response. */
export interface TimeseriesResponse {
  metric: string;
  start: string | null;
  end: string | null;
  points: TimeseriesPoint[];
}

// ---------------------------------------------------------------------------
// Admin panel (M4.5) — mirrors app/models.py (all org-scoped)
// ---------------------------------------------------------------------------

/** `GET /v1/orgs/{id}/usage` response. */
export interface UsageResponse {
  plan: string;
  used: number;
  limit: number | null;
  period_start: string;
}

/** API key metadata (never the secret). */
export interface ApiKeyResponse {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  revoked: boolean;
}

/** API key metadata + the one-time plaintext secret (create only). */
export interface ApiKeyCreatedResponse extends ApiKeyResponse {
  api_key: string;
}

/** A registered outbound webhook (never the signing secret). */
export interface WebhookResponse {
  id: string;
  url: string;
  event_types: string[];
  active: boolean;
}

/** A newly created webhook + its one-time signing secret. */
export interface WebhookCreatedResponse extends WebhookResponse {
  secret: string;
}

/** A routing rule. */
export interface RoutingRuleResponse {
  id: string;
  name: string;
  position: number;
  conditions: Record<string, string>;
  actions: Record<string, unknown>;
  active: boolean;
}

/** An SLA policy (resolution deadline for a priority). */
export interface SlaPolicyResponse {
  id: string;
  priority: string;
  resolution_minutes: number;
  active: boolean;
}
