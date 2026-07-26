import Link from "next/link";

import type { Session } from "@/lib/auth/session";
import { LogoutButton } from "@/components/LogoutButton";
import { OrgSwitcher } from "@/components/OrgSwitcher";

/** Authenticated application chrome: top bar + main content area. */
export function AppShell({ session, children }: { session: Session; children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-4">
            <Link href="/dashboard" className="font-semibold tracking-tight">
              TriageAI
            </Link>
            {session.activeOrg ? (
              <nav className="flex items-center gap-3 text-sm text-neutral-600 dark:text-neutral-300">
                <Link href="/tickets" className="hover:underline">
                  Tickets
                </Link>
                <Link href="/analyze" className="hover:underline">
                  Analyze
                </Link>
                <Link href="/analytics" className="hover:underline">
                  Analytics
                </Link>
                <Link href="/settings" className="hover:underline">
                  Settings
                </Link>
              </nav>
            ) : null}
          </div>
          <div className="flex items-center gap-4">
            {session.orgs.length > 1 ? (
              <OrgSwitcher orgs={session.orgs} activeOrgId={session.activeOrg?.id ?? null} />
            ) : null}
            <span className="hidden text-sm text-neutral-500 sm:inline dark:text-neutral-400">
              {session.user.email}
            </span>
            <LogoutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
