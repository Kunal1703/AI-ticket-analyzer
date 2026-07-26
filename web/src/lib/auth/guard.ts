/**
 * Server-only auth guards for pages and Server Actions in the `(app)` group.
 *
 * `getAuthedContext()` guarantees a signed-in user *with an active org* — the
 * minimum needed to make tenant-scoped backend calls. It redirects rather than
 * returning null so callers can use its result directly.
 */

import "server-only";

import { redirect } from "next/navigation";

import { getSession } from "./session";

export interface AuthedContext {
  token: string;
  orgId: string;
}

/**
 * Return the current user's access token and active org id, or redirect:
 * to `/login` when unauthenticated, or to `/dashboard` (to create/select an
 * org) when signed in but no org is active.
 */
export async function getAuthedContext(): Promise<AuthedContext> {
  const session = await getSession();
  if (!session) redirect("/login");
  if (!session.activeOrg) redirect("/dashboard");
  return { token: session.token, orgId: session.activeOrg.id };
}
