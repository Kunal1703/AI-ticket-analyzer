/**
 * Typed wrappers over the org-scoped admin endpoints (API keys, webhooks,
 * routing rules, SLA policies, usage). Server-only.
 *
 * These backend routes take `org_id` in the **path** and authorize via the user
 * JWT (`require_org_membership` / `require_role`), so we pass the bearer token
 * and put the org id in the URL — no `X-Organization-Id` header needed.
 */

import "server-only";

import { apiFetch } from "./http";
import type {
  ApiKeyCreatedResponse,
  ApiKeyResponse,
  RoutingRuleResponse,
  SlaPolicyResponse,
  UsageResponse,
  WebhookCreatedResponse,
  WebhookResponse,
} from "./types";

// --- Usage -----------------------------------------------------------------

export function getUsage(token: string, orgId: string): Promise<UsageResponse> {
  return apiFetch<UsageResponse>(`/v1/orgs/${orgId}/usage`, { token });
}

// --- API keys --------------------------------------------------------------

export function listApiKeys(token: string, orgId: string): Promise<ApiKeyResponse[]> {
  return apiFetch<ApiKeyResponse[]>(`/v1/orgs/${orgId}/api-keys`, { token });
}

export function createApiKey(
  token: string,
  orgId: string,
  body: { name: string; scopes: string[] },
): Promise<ApiKeyCreatedResponse> {
  return apiFetch<ApiKeyCreatedResponse>(`/v1/orgs/${orgId}/api-keys`, {
    method: "POST",
    token,
    body,
  });
}

export function revokeApiKey(token: string, orgId: string, keyId: string): Promise<void> {
  return apiFetch<void>(`/v1/orgs/${orgId}/api-keys/${keyId}`, { method: "DELETE", token });
}

// --- Webhooks --------------------------------------------------------------

export function listWebhooks(token: string, orgId: string): Promise<WebhookResponse[]> {
  return apiFetch<WebhookResponse[]>(`/v1/orgs/${orgId}/webhooks`, { token });
}

export function createWebhook(
  token: string,
  orgId: string,
  body: { url: string; event_types: string[] },
): Promise<WebhookCreatedResponse> {
  return apiFetch<WebhookCreatedResponse>(`/v1/orgs/${orgId}/webhooks`, {
    method: "POST",
    token,
    body,
  });
}

export function deleteWebhook(token: string, orgId: string, id: string): Promise<void> {
  return apiFetch<void>(`/v1/orgs/${orgId}/webhooks/${id}`, { method: "DELETE", token });
}

// --- Routing rules ---------------------------------------------------------

export function listRoutingRules(token: string, orgId: string): Promise<RoutingRuleResponse[]> {
  return apiFetch<RoutingRuleResponse[]>(`/v1/orgs/${orgId}/routing-rules`, { token });
}

export function createRoutingRule(
  token: string,
  orgId: string,
  body: {
    name: string;
    position: number;
    conditions: Record<string, string>;
    actions: Record<string, unknown>;
  },
): Promise<RoutingRuleResponse> {
  return apiFetch<RoutingRuleResponse>(`/v1/orgs/${orgId}/routing-rules`, {
    method: "POST",
    token,
    body,
  });
}

export function deleteRoutingRule(token: string, orgId: string, id: string): Promise<void> {
  return apiFetch<void>(`/v1/orgs/${orgId}/routing-rules/${id}`, { method: "DELETE", token });
}

// --- SLA policies ----------------------------------------------------------

export function listSlaPolicies(token: string, orgId: string): Promise<SlaPolicyResponse[]> {
  return apiFetch<SlaPolicyResponse[]>(`/v1/orgs/${orgId}/sla-policies`, { token });
}

export function createSlaPolicy(
  token: string,
  orgId: string,
  body: { priority: string; resolution_minutes: number },
): Promise<SlaPolicyResponse> {
  return apiFetch<SlaPolicyResponse>(`/v1/orgs/${orgId}/sla-policies`, {
    method: "POST",
    token,
    body,
  });
}

export function deleteSlaPolicy(token: string, orgId: string, id: string): Promise<void> {
  return apiFetch<void>(`/v1/orgs/${orgId}/sla-policies/${id}`, { method: "DELETE", token });
}
