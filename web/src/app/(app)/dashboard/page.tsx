import Link from "next/link";
import { redirect } from "next/navigation";

import { CreateOrgForm } from "@/components/CreateOrgForm";
import { getSession } from "@/lib/auth/session";

/** Workspace entry points. Live cards link; upcoming ones show a milestone tag. */
const FEATURES = [
  {
    title: "Tickets",
    body: "Browse, filter, and triage your organization's tickets.",
    href: "/tickets",
    milestone: "ready",
  },
  {
    title: "New analysis",
    body: "Analyze a support message with the AI co-pilot.",
    href: "/analyze",
    milestone: "ready",
  },
  {
    title: "Analytics",
    body: "Summary metrics, distributions, and daily trends.",
    href: "/analytics",
    milestone: "ready",
  },
];

export default async function DashboardPage() {
  const session = await getSession();
  if (!session) redirect("/login");

  const greeting = session.user.name?.trim() || session.user.email;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome, {greeting}</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          This is the TriageAI workspace scaffold (M4.2). Feature screens arrive in later milestones.
        </p>
      </div>

      {session.orgs.length === 0 ? (
        <section className="rounded-lg border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="text-lg font-medium">Create your organization</h2>
          <p className="mb-4 mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            You need an organization before you can analyze tickets or issue API keys.
          </p>
          <CreateOrgForm />
        </section>
      ) : !session.activeOrg ? (
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Select an organization from the switcher in the top bar to continue.
        </section>
      ) : (
        <>
          <section className="rounded-lg border border-neutral-200 bg-white p-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
            Active organization: <span className="font-medium">{session.activeOrg.name}</span>{" "}
            <span className="text-neutral-500 dark:text-neutral-400">
              · plan: {session.activeOrg.plan}
            </span>
          </section>

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => {
              const card = (
                <>
                  <div className="flex items-center justify-between">
                    <h3 className="font-medium">{f.title}</h3>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        f.milestone === "ready"
                          ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
                          : "bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400"
                      }`}
                    >
                      {f.milestone}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-400">{f.body}</p>
                </>
              );
              const cls =
                "block rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900";
              return f.href ? (
                <Link key={f.title} href={f.href} className={`${cls} transition-colors hover:border-neutral-400 dark:hover:border-neutral-600`}>
                  {card}
                </Link>
              ) : (
                <div key={f.title} className={cls}>
                  {card}
                </div>
              );
            })}
          </section>
        </>
      )}
    </div>
  );
}
