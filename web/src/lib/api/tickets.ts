/**
 * Typed wrappers over the backend ticket endpoints (`/v1/tickets`, `/v1/analyze`).
 * Server-only. Every call is tenant-scoped: it carries the bearer token and the
 * active org's `X-Organization-Id` (via `apiFetch`).
 */

import "server-only";

import { apiFetch } from "./http";
import type {
  AnalyzeResponse,
  CreateFeedbackBody,
  FeedbackResponse,
  PaginatedTickets,
  RoutingResult,
  TicketDetail,
  UpdateTicketBody,
} from "./types";

export interface ListTicketsParams {
  limit: number;
  offset: number;
  category?: string;
  priority?: string;
  status?: string;
  assignee?: string;
  source?: string;
  search?: string;
  sort?: string;
}

function auth(token: string, orgId: string) {
  return { token, orgId } as const;
}

export function listTickets(
  token: string,
  orgId: string,
  params: ListTicketsParams,
): Promise<PaginatedTickets> {
  const qs = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.category) qs.set("category", params.category);
  if (params.priority) qs.set("priority", params.priority);
  if (params.status) qs.set("status", params.status);
  if (params.assignee) qs.set("assignee", params.assignee);
  if (params.source) qs.set("source", params.source);
  if (params.search) qs.set("search", params.search);
  if (params.sort) qs.set("sort", params.sort);
  return apiFetch<PaginatedTickets>(`/v1/tickets?${qs.toString()}`, auth(token, orgId));
}

export function getTicket(token: string, orgId: string, id: string): Promise<TicketDetail> {
  return apiFetch<TicketDetail>(`/v1/tickets/${id}`, auth(token, orgId));
}

export function updateTicket(
  token: string,
  orgId: string,
  id: string,
  body: UpdateTicketBody,
): Promise<TicketDetail> {
  return apiFetch<TicketDetail>(`/v1/tickets/${id}`, {
    ...auth(token, orgId),
    method: "PATCH",
    body,
  });
}

export function reanalyzeTicket(
  token: string,
  orgId: string,
  id: string,
): Promise<AnalyzeResponse> {
  return apiFetch<AnalyzeResponse>(`/v1/tickets/${id}/reanalyze`, {
    ...auth(token, orgId),
    method: "POST",
  });
}

export function listFeedback(
  token: string,
  orgId: string,
  id: string,
): Promise<FeedbackResponse[]> {
  return apiFetch<FeedbackResponse[]>(`/v1/tickets/${id}/feedback`, auth(token, orgId));
}

export function createFeedback(
  token: string,
  orgId: string,
  id: string,
  body: CreateFeedbackBody,
): Promise<FeedbackResponse> {
  return apiFetch<FeedbackResponse>(`/v1/tickets/${id}/feedback`, {
    ...auth(token, orgId),
    method: "POST",
    body,
  });
}

export function routeTicket(token: string, orgId: string, id: string): Promise<RoutingResult> {
  return apiFetch<RoutingResult>(`/v1/tickets/${id}/route`, {
    ...auth(token, orgId),
    method: "POST",
  });
}

export function analyzeText(
  token: string,
  orgId: string,
  ticket: string,
): Promise<AnalyzeResponse> {
  return apiFetch<AnalyzeResponse>("/v1/analyze", {
    ...auth(token, orgId),
    method: "POST",
    body: { ticket },
  });
}
