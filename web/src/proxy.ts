/**
 * Proxy — in Next.js 16 this replaces Middleware (same functionality, renamed).
 *
 * It performs *optimistic* auth routing based only on cookie presence (no
 * network, no token validation — that happens in the session DAL). It:
 *  - sends unauthenticated visitors of protected routes to /login,
 *  - refreshes an expired access cookie (present refresh, absent access) by
 *    redirecting through /api/auth/refresh,
 *  - keeps already-signed-in users away from the login/signup pages.
 *
 * Real authorization is still enforced server-side by `getSession()` on every
 * protected page — the proxy is only a fast redirect layer.
 */

import { NextResponse, type NextRequest } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth/cookie-config";

const PROTECTED_PREFIXES = ["/dashboard", "/tickets", "/analyze", "/analytics", "/settings"];
const AUTH_PAGES = ["/login", "/signup"];

function matchesAny(pathname: string, prefixes: string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const hasAccess = Boolean(request.cookies.get(ACCESS_COOKIE)?.value);
  const hasRefresh = Boolean(request.cookies.get(REFRESH_COOKIE)?.value);

  if (matchesAny(pathname, PROTECTED_PREFIXES)) {
    if (!hasRefresh) {
      const url = new URL("/login", request.url);
      if (pathname !== "/dashboard") url.searchParams.set("next", pathname);
      return NextResponse.redirect(url);
    }
    if (!hasAccess) {
      const url = new URL("/api/auth/refresh", request.url);
      url.searchParams.set("next", pathname);
      return NextResponse.redirect(url);
    }
  }

  if (matchesAny(pathname, AUTH_PAGES) && hasRefresh) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard",
    "/dashboard/:path*",
    "/tickets",
    "/tickets/:path*",
    "/analyze",
    "/analytics",
    "/settings",
    "/settings/:path*",
    "/login",
    "/signup",
  ],
};
