/**
 * Server-only helpers for reading and writing the session cookies via the
 * Next.js async `cookies()` API. Cookies can only be *written* from a Server
 * Action, Route Handler, or the proxy — never from a Server Component render —
 * so these setters are called from those contexts.
 */

import "server-only";

import { cookies } from "next/headers";

import type { TokenResponse } from "../api/types";
import {
  ACCESS_COOKIE,
  ACCESS_MAX_AGE,
  ACTIVE_ORG_COOKIE,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE,
  cookieOptions,
} from "./cookie-config";

/** Persist a freshly issued token pair as httpOnly cookies. */
export async function setSessionCookies(tokens: TokenResponse): Promise<void> {
  const store = await cookies();
  store.set(ACCESS_COOKIE, tokens.access_token, cookieOptions(ACCESS_MAX_AGE));
  store.set(REFRESH_COOKIE, tokens.refresh_token, cookieOptions(REFRESH_MAX_AGE));
}

/** Record which organization the user is currently operating as. */
export async function setActiveOrgCookie(orgId: string): Promise<void> {
  const store = await cookies();
  store.set(ACTIVE_ORG_COOKIE, orgId, cookieOptions(REFRESH_MAX_AGE));
}

/** Read the current access token, if any. */
export async function getAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_COOKIE)?.value;
}

/** Read the current refresh token, if any. */
export async function getRefreshToken(): Promise<string | undefined> {
  return (await cookies()).get(REFRESH_COOKIE)?.value;
}

/** Read the active organization id, if one has been selected. */
export async function getActiveOrgId(): Promise<string | undefined> {
  return (await cookies()).get(ACTIVE_ORG_COOKIE)?.value;
}

/** Clear every session cookie (logout, or an unrecoverable auth failure). */
export async function clearSessionCookies(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
  store.delete(ACTIVE_ORG_COOKIE);
}
