/**
 * Pure parsing/serialization of the tickets-list query parameters (Next.js-free,
 * unit-tested). The backend validates `category`/`priority`/`status`/`sort`
 * against fixed enums, so we only forward recognized values; free-text
 * `assignee`/`source`/`search` are trimmed and passed through (length-bounded by
 * the backend). `limit`/`offset` are clamped to the accepted ranges.
 */

import {
  TICKET_CATEGORIES,
  TICKET_PRIORITIES,
  TICKET_SORTS,
  TICKET_STATUSES,
} from "../api/types";

export const DEFAULT_LIMIT = 20;
export const DEFAULT_SORT = "-created_at";

export interface TicketListParams {
  limit: number;
  offset: number;
  category?: string;
  priority?: string;
  status?: string;
  assignee?: string;
  source?: string;
  search?: string;
  sort: string;
}

type RawParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function clampInt(raw: string | undefined, fallback: number, min: number, max: number): number {
  const n = Number.parseInt(raw ?? "", 10);
  if (Number.isNaN(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function oneOf(value: string | undefined, allowed: readonly string[]): string | undefined {
  return value && allowed.includes(value) ? value : undefined;
}

function text(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

/** Parse raw search params into validated, clamped list parameters. */
export function parseTicketListParams(sp: RawParams): TicketListParams {
  return {
    limit: clampInt(first(sp.limit), DEFAULT_LIMIT, 1, 100),
    offset: clampInt(first(sp.offset), 0, 0, Number.MAX_SAFE_INTEGER),
    category: oneOf(first(sp.category), TICKET_CATEGORIES),
    priority: oneOf(first(sp.priority), TICKET_PRIORITIES),
    status: oneOf(first(sp.status), TICKET_STATUSES),
    assignee: text(first(sp.assignee)),
    source: text(first(sp.source)),
    search: text(first(sp.search)),
    sort: oneOf(first(sp.sort), TICKET_SORTS) ?? DEFAULT_SORT,
  };
}

/** Build a `/tickets` href with the given (partial) params merged in. */
export function buildTicketsHref(params: Partial<TicketListParams>): string {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.priority) qs.set("priority", params.priority);
  if (params.status) qs.set("status", params.status);
  if (params.assignee) qs.set("assignee", params.assignee);
  if (params.source) qs.set("source", params.source);
  if (params.search) qs.set("search", params.search);
  if (params.sort && params.sort !== DEFAULT_SORT) qs.set("sort", params.sort);
  if (params.limit !== undefined && params.limit !== DEFAULT_LIMIT) {
    qs.set("limit", String(params.limit));
  }
  if (params.offset) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return query ? `/tickets?${query}` : "/tickets";
}

/** Whether any filter (not pagination/sort) is active — drives the Clear link. */
export function hasActiveFilters(params: TicketListParams): boolean {
  return Boolean(
    params.category || params.priority || params.status || params.assignee || params.source || params.search,
  );
}
