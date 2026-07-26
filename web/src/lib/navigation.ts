/**
 * Navigation helpers shared by the proxy, Server Actions, and Route Handlers.
 * Next.js-free so the open-redirect guard is unit-testable.
 */

/**
 * Sanitize a caller-supplied `next` destination to prevent open redirects.
 *
 * Only same-origin *relative* paths are allowed: the value must start with a
 * single "/" (not "//", which browsers treat as protocol-relative and would
 * escape our origin). Anything else — absolute URLs, protocol-relative URLs,
 * backslash tricks, or empty input — falls back to {@link fallback}.
 */
export function sanitizeNextPath(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next) return fallback;
  if (!next.startsWith("/")) return fallback;
  if (next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next;
}
