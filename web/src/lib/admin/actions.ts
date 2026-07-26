"use server";

/**
 * Server Actions for the admin panel (M4.5). Each resolves the authed org
 * context, calls an org-scoped backend endpoint, maps errors to a user-safe
 * message, and revalidates the affected settings page. Create actions that mint
 * a one-time secret return it in the state (the client reveals it once) rather
 * than redirecting.
 */

import { revalidatePath } from "next/cache";

import {
  createApiKey,
  createRoutingRule,
  createSlaPolicy,
  createWebhook,
  deleteRoutingRule,
  deleteSlaPolicy,
  deleteWebhook,
  revokeApiKey,
} from "../api/admin";
import { ApiError } from "../api/errors";
import { getAuthedContext } from "../auth/guard";
import { buildRoutingActions, buildRoutingConditions, parseCsvList } from "./parse";

export interface AdminState {
  error?: string;
  ok?: boolean;
}

export interface SecretState extends AdminState {
  /** A one-time secret to reveal (API key plaintext / webhook signing secret). */
  secret?: string;
}

/** Map a backend failure to a concise, user-safe message. */
function describe(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return "Your session expired. Please log in again.";
      case 403:
        return "You don't have permission to do that (owner or admin required).";
      case 404:
        return "That item no longer exists.";
      case 422:
        return "Please check the details you entered.";
      case 503:
        return "The service is temporarily unavailable.";
      default:
        return error.message || "Something went wrong.";
    }
  }
  return "Something went wrong.";
}

// --- API keys --------------------------------------------------------------

export async function createApiKeyAction(
  _prev: SecretState,
  formData: FormData,
): Promise<SecretState> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { error: "A name is required." };
  const scopes = parseCsvList(String(formData.get("scopes") ?? ""));
  const { token, orgId } = await getAuthedContext();
  try {
    const created = await createApiKey(token, orgId, {
      name,
      scopes: scopes.length > 0 ? scopes : ["analyze"],
    });
    revalidatePath("/settings/api-keys");
    return { ok: true, secret: created.api_key };
  } catch (error) {
    return { error: describe(error) };
  }
}

export async function revokeApiKeyAction(
  _prev: AdminState,
  formData: FormData,
): Promise<AdminState> {
  const id = String(formData.get("id") ?? "");
  const { token, orgId } = await getAuthedContext();
  try {
    await revokeApiKey(token, orgId, id);
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath("/settings/api-keys");
  return { ok: true };
}

// --- Webhooks --------------------------------------------------------------

export async function createWebhookAction(
  _prev: SecretState,
  formData: FormData,
): Promise<SecretState> {
  const url = String(formData.get("url") ?? "").trim();
  if (!url) return { error: "A URL is required." };
  const eventTypes = parseCsvList(String(formData.get("event_types") ?? ""));
  const { token, orgId } = await getAuthedContext();
  try {
    const created = await createWebhook(token, orgId, {
      url,
      event_types: eventTypes.length > 0 ? eventTypes : ["batch.completed"],
    });
    revalidatePath("/settings/webhooks");
    return { ok: true, secret: created.secret };
  } catch (error) {
    return { error: describe(error) };
  }
}

export async function deleteWebhookAction(
  _prev: AdminState,
  formData: FormData,
): Promise<AdminState> {
  const id = String(formData.get("id") ?? "");
  const { token, orgId } = await getAuthedContext();
  try {
    await deleteWebhook(token, orgId, id);
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath("/settings/webhooks");
  return { ok: true };
}

// --- Routing rules ---------------------------------------------------------

export async function createRoutingRuleAction(
  _prev: AdminState,
  formData: FormData,
): Promise<AdminState> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { error: "A name is required." };
  const position = Number.parseInt(String(formData.get("position") ?? "0"), 10);
  if (Number.isNaN(position) || position < 0) return { error: "Position must be 0 or greater." };

  const conditions = buildRoutingConditions(
    String(formData.get("condition_category") ?? ""),
    String(formData.get("condition_priority") ?? ""),
  );
  const actions = buildRoutingActions(
    String(formData.get("action_assignee") ?? ""),
    String(formData.get("action_tags") ?? ""),
  );

  const { token, orgId } = await getAuthedContext();
  try {
    await createRoutingRule(token, orgId, { name, position, conditions, actions });
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath("/settings/routing");
  return { ok: true };
}

export async function deleteRoutingRuleAction(
  _prev: AdminState,
  formData: FormData,
): Promise<AdminState> {
  const id = String(formData.get("id") ?? "");
  const { token, orgId } = await getAuthedContext();
  try {
    await deleteRoutingRule(token, orgId, id);
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath("/settings/routing");
  return { ok: true };
}

// --- SLA policies ----------------------------------------------------------

export async function createSlaPolicyAction(
  _prev: AdminState,
  formData: FormData,
): Promise<AdminState> {
  const priority = String(formData.get("priority") ?? "").trim();
  if (!priority) return { error: "A priority is required." };
  const minutes = Number.parseInt(String(formData.get("resolution_minutes") ?? ""), 10);
  if (Number.isNaN(minutes) || minutes < 1) return { error: "Resolution minutes must be at least 1." };

  const { token, orgId } = await getAuthedContext();
  try {
    await createSlaPolicy(token, orgId, { priority, resolution_minutes: minutes });
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath("/settings/routing");
  return { ok: true };
}

export async function deleteSlaPolicyAction(
  _prev: AdminState,
  formData: FormData,
): Promise<AdminState> {
  const id = String(formData.get("id") ?? "");
  const { token, orgId } = await getAuthedContext();
  try {
    await deleteSlaPolicy(token, orgId, id);
  } catch (error) {
    return { error: describe(error) };
  }
  revalidatePath("/settings/routing");
  return { ok: true };
}
