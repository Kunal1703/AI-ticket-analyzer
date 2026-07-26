import { redirect } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import { getSession } from "@/lib/auth/session";

/**
 * Protected layout. The real auth gate lives here (and in each page via
 * `getSession()`), not only in the proxy: an unauthenticated request never
 * renders app content. `getSession()` is memoized, so the child page reusing it
 * costs no extra backend call.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");
  return <AppShell session={session}>{children}</AppShell>;
}
