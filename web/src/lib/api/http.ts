/**
 * Server-only HTTP client for the FastAPI backend.
 *
 * This is the single seam through which the Next.js server talks to the API.
 * It attaches the bearer token and optional `X-Organization-Id` header, sends/
 * receives JSON, and translates non-2xx responses into {@link ApiError} using
 * the backend's error envelope. Mirrors the "one client, errors translate at
 * the boundary" discipline the backend itself follows.
 */

import "server-only";

import { API_BASE_URL } from "../config";
import { apiErrorFromBody, ApiError } from "./errors";

export interface ApiRequest {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON-serializable request body. */
  body?: unknown;
  /** Bearer access token to authenticate the call. */
  token?: string;
  /** Active organization id → `X-Organization-Id` (tenant selection). */
  orgId?: string;
}

/**
 * Perform a JSON request against `path` (e.g. "/v1/auth/me") and return the
 * parsed response. Throws {@link ApiError} on any non-2xx status, and on a
 * transport failure (backend unreachable).
 */
export async function apiFetch<T>(path: string, req: ApiRequest = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (req.body !== undefined) headers["Content-Type"] = "application/json";
  if (req.token) headers["Authorization"] = `Bearer ${req.token}`;
  if (req.orgId) headers["X-Organization-Id"] = req.orgId;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: req.method ?? "GET",
      headers,
      body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
      // Auth/tenant data is per-user and must never be cached across requests.
      cache: "no-store",
    });
  } catch {
    throw new ApiError(503, "backend_unreachable", "The backend is unreachable.", null);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const parsed: unknown = text ? safeJsonParse(text) : undefined;

  if (!response.ok) {
    throw apiErrorFromBody(response.status, parsed);
  }
  return parsed as T;
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}
