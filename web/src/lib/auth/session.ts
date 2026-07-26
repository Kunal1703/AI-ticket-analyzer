/**
 * Server-only session Data Access Layer (DAL).
 *
 * `getSession()` is the single source of truth for "who is the current user and
 * which org are they acting as". It reads the httpOnly access cookie, calls the
 * backend, and returns a resolved session (or null). It is wrapped in React's
 * `cache` so multiple calls within one render (layout + page + components) hit
 * the backend once.
 *
 * Token *refresh* is not done here: a Server Component cannot write cookies, so
 * refresh is handled upstream by the proxy (which redirects an expired access
 * cookie to `/api/auth/refresh`). Here, a 401 simply means "no session".
 */

import "server-only";

import { cache } from "react";

import { listOrgs } from "../api/orgs";
import type { OrgResponse, UserResponse } from "../api/types";
import { me } from "../api/auth";
import { ApiError } from "../api/errors";
import { getAccessToken, getActiveOrgId } from "./cookies";

export interface Session {
  user: UserResponse;
  orgs: OrgResponse[];
  /** The org the user is currently acting as, or null if none is selected. */
  activeOrg: OrgResponse | null;
  /** The raw access token, for making further backend calls this request. */
  token: string;
}

/**
 * Resolve the current session, or null when unauthenticated. Never throws for
 * an auth failure (401 → null); a transport/backend error also resolves to null
 * so protected pages fall back to the (public) login screen rather than erroring.
 */
export const getSession = cache(async (): Promise<Session | null> => {
  const token = await getAccessToken();
  if (!token) return null;

  let user: UserResponse;
  try {
    user = await me(token);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    // Backend unreachable or unexpected: treat as no session for this render.
    return null;
  }

  const orgs = await safeListOrgs(token);
  const activeOrg = resolveActiveOrg(orgs, await getActiveOrgId());

  return { user, orgs, activeOrg, token };
});

async function safeListOrgs(token: string): Promise<OrgResponse[]> {
  try {
    return await listOrgs(token);
  } catch {
    return [];
  }
}

/**
 * Pick the active org: the cookie's org if the user still belongs to it,
 * otherwise the sole org when there is exactly one, otherwise none.
 */
function resolveActiveOrg(orgs: OrgResponse[], cookieOrgId: string | undefined): OrgResponse | null {
  if (cookieOrgId) {
    const match = orgs.find((o) => o.id === cookieOrgId);
    if (match) return match;
  }
  if (orgs.length === 1) return orgs[0];
  return null;
}
