"use server";

/**
 * Server Actions for the agent workspace (M4.3). Each resolves the authed tenant
 * context, calls the backend, and revalidates the affected paths. All mutations
 * are backed by *existing* endpoints — no backend changes in this milestone.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError } from "../api/errors";
import {
  analyzeText,
  createFeedback,
  reanalyzeTicket,
  routeTicket,
  updateTicket,
} from "../api/tickets";
import { TICKET_STATUSES } from "../api/types";
import type { AnalyzeResponse, FeedbackRating, TicketAnalysis, TicketStatus } from "../api/types";
import { getAuthedContext } from "../auth/guard";

export interface ActionState {
  error?: string;
  ok?: boolean;
}

export interface AnalyzeState extends ActionState {
  result?: TicketAnalysis;
}

/** Concise, user-safe message for a backend failure in the workspace. */
function describe(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return "Your session expired. Please log in again.";
      case 402:
        return "Monthly analysis quota reached for this plan.";
      case 403:
        return "You don't have permission to do that.";
      case 404:
        return "That ticket no longer exists.";
      case 409:
        return "This ticket has no analysis to route on yet.";
      case 429:
        return "The AI provider is rate-limited. Try again shortly.";
      case 502:
      case 503:
      case 504:
        return "The analysis service is temporarily unavailable.";
      default:
        return error.message || "Something went wrong.";
    }
  }
  return "Something went wrong.";
}

export async function reanalyzeAction(_prev: ActionState, formData: FormData): Promise<ActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  if (!ticketId) return { error: "Missing ticket." };
  const { token, orgId } = await getAuthedContext();
  try {
    await reanalyzeTicket(token, orgId, ticketId);
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath(`/tickets/${ticketId}`);
  revalidatePath("/tickets");
  return { ok: true };
}

export async function applyRoutingAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  if (!ticketId) return { error: "Missing ticket." };
  const { token, orgId } = await getAuthedContext();
  try {
    await routeTicket(token, orgId, ticketId);
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath(`/tickets/${ticketId}`);
  revalidatePath("/tickets");
  return { ok: true };
}

export async function submitFeedbackAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  const rating = String(formData.get("rating") ?? "") as FeedbackRating;
  if (!ticketId) return { error: "Missing ticket." };
  if (rating !== "positive" && rating !== "negative") {
    return { error: "Please choose a rating." };
  }

  const analysisId = String(formData.get("analysis_id") ?? "").trim();
  const correctedCategory = String(formData.get("corrected_category") ?? "").trim();
  const correctedPriority = String(formData.get("corrected_priority") ?? "").trim();
  const comment = String(formData.get("comment") ?? "").trim();

  const { token, orgId } = await getAuthedContext();
  try {
    await createFeedback(token, orgId, ticketId, {
      rating,
      analysis_id: analysisId || undefined,
      corrected_category: correctedCategory || undefined,
      corrected_priority: correctedPriority || undefined,
      comment: comment || undefined,
    });
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath(`/tickets/${ticketId}`);
  return { ok: true };
}

export async function updateStatusAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  const status = String(formData.get("status") ?? "");
  if (!ticketId) return { error: "Missing ticket." };
  if (!(TICKET_STATUSES as readonly string[]).includes(status)) {
    return { error: "Invalid status." };
  }
  const { token, orgId } = await getAuthedContext();
  try {
    await updateTicket(token, orgId, ticketId, { status: status as TicketStatus });
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath(`/tickets/${ticketId}`);
  revalidatePath("/tickets");
  return { ok: true };
}

export async function updateAssigneeAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  if (!ticketId) return { error: "Missing ticket." };
  // Empty input clears the assignee ({assignee: null}); a value sets it.
  const assignee = String(formData.get("assignee") ?? "").trim();
  const { token, orgId } = await getAuthedContext();
  try {
    await updateTicket(token, orgId, ticketId, { assignee: assignee || null });
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath(`/tickets/${ticketId}`);
  revalidatePath("/tickets");
  return { ok: true };
}

export async function analyzeAction(
  _prev: AnalyzeState,
  formData: FormData,
): Promise<AnalyzeState> {
  const ticket = String(formData.get("ticket") ?? "").trim();
  if (!ticket) return { error: "Enter some ticket text to analyze." };
  if (ticket.length > 5000) return { error: "Ticket text must be 5000 characters or fewer." };

  const { token, orgId } = await getAuthedContext();
  let result: AnalyzeResponse;
  try {
    result = await analyzeText(token, orgId, ticket);
  } catch (error) {
    return { error: describe(error) };
  }
  // A new ticket now exists under the org; refresh the list, then deep-link to
  // it (M3.6 returns the ticket_id). Falls back to inline result if no DB.
  revalidatePath("/tickets");
  if (result.ticket_id) redirect(`/tickets/${result.ticket_id}`);
  return { ok: true, result };
}
