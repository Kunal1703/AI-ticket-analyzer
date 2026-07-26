/**
 * API error handling for the BFF.
 *
 * The backend returns a stable error envelope
 * (`{"error": {code, message, request_id, details?}}`) with a preserved HTTP
 * status. `ApiError` carries both so callers (Server Actions) can map them to
 * user-facing messages. This module is deliberately free of any Next.js imports
 * so its parsing logic is unit-testable in isolation.
 */

import type { ErrorEnvelope } from "./types";

/** Error thrown by the API client for any non-2xx backend response. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

/** Type guard for the backend error envelope shape. */
export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const err = (value as { error?: unknown }).error;
  if (typeof err !== "object" || err === null) return false;
  const e = err as Record<string, unknown>;
  return typeof e.code === "string" && typeof e.message === "string";
}

/**
 * Build an {@link ApiError} from a status code and a parsed response body.
 * Falls back to a generic code/message when the body is not a recognized
 * envelope (e.g. a proxy returned plain text, or the body was empty).
 */
export function apiErrorFromBody(status: number, body: unknown): ApiError {
  if (isErrorEnvelope(body)) {
    const { code, message, request_id } = body.error;
    return new ApiError(status, code, message, request_id ?? null);
  }
  return new ApiError(status, "unexpected_error", `Request failed (${status})`, null);
}
