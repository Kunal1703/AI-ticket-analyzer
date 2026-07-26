/**
 * Cookie names and option builders for the session cookies. Next.js-free so the
 * option logic is unit-testable; the thin `next/headers` wrappers live in
 * `cookies.ts`.
 *
 * Three httpOnly cookies model the session:
 *  - access token  (short-lived; its lifetime tracks the backend access TTL)
 *  - refresh token (long-lived; used to mint a new pair when access expires)
 *  - active org id  (which organization the user is currently operating as)
 *
 * All are httpOnly: tokens must never be readable by browser JS (the whole
 * point of the BFF), and the active-org id is read server-side to set the
 * `X-Organization-Id` header on backend calls.
 */

import { COOKIES_SECURE } from "../config";

export const ACCESS_COOKIE = "atk_access";
export const REFRESH_COOKIE = "atk_refresh";
export const ACTIVE_ORG_COOKIE = "atk_org";

/**
 * Cookie lifetimes (seconds). These mirror the backend defaults
 * (`access_token_ttl_seconds` = 900, `refresh_token_ttl_seconds` = 1_209_600)
 * so a browser-dropped access cookie is a reliable "needs refresh" signal.
 */
export const ACCESS_MAX_AGE = 900; // 15 minutes
export const REFRESH_MAX_AGE = 1_209_600; // 14 days

export interface SessionCookieOptions {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: "/";
  maxAge: number;
}

/** Standard options for a session cookie with the given lifetime. */
export function cookieOptions(maxAge: number): SessionCookieOptions {
  return {
    httpOnly: true,
    secure: COOKIES_SECURE,
    sameSite: "lax",
    path: "/",
    maxAge,
  };
}
