/**
 * Token refresh Route Handler.
 *
 * Route Handlers (unlike Server Components) can write cookies, so this is where
 * an expired access token is renewed. The proxy redirects here with a `next`
 * destination when it sees a refresh cookie but no access cookie. On success we
 * mint a new pair, store it, and bounce back to `next`; on failure we clear the
 * session and send the user to log in.
 */

import { redirect } from "next/navigation";
import type { NextRequest } from "next/server";

import { refresh } from "@/lib/api/auth";
import { clearSessionCookies, getRefreshToken, setSessionCookies } from "@/lib/auth/cookies";
import { sanitizeNextPath } from "@/lib/navigation";

export async function GET(request: NextRequest): Promise<never> {
  const next = sanitizeNextPath(request.nextUrl.searchParams.get("next"));
  const refreshToken = await getRefreshToken();

  if (!refreshToken) {
    await clearSessionCookies();
    redirect("/login");
  }

  let tokens;
  try {
    tokens = await refresh(refreshToken);
  } catch {
    await clearSessionCookies();
    redirect("/login");
  }

  await setSessionCookies(tokens);
  redirect(next);
}
