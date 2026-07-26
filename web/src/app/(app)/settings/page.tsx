import { redirect } from "next/navigation";

import { ErrorPanel } from "@/components/ErrorPanel";
import { getUsage } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/errors";
import type { UsageResponse } from "@/lib/api/types";
import { getSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";

export default async function SettingsOverviewPage() {
  const session = await getSession();
  if (!session?.activeOrg) redirect("/dashboard");
  const org = session.activeOrg;

  let usage: UsageResponse | null = null;
  let usageError: string | null = null;
  try {
    usage = await getUsage(session.token, org.id);
  } catch (error) {
    usageError = error instanceof ApiError ? error.message : "Could not load usage.";
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          Organization
        </h2>
        <dl className="space-y-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-neutral-500 dark:text-neutral-400">Name</dt>
            <dd className="font-medium">{org.name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-neutral-500 dark:text-neutral-400">Slug</dt>
            <dd className="font-mono text-xs">{org.slug}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-neutral-500 dark:text-neutral-400">Plan</dt>
            <dd className="font-medium capitalize">{org.plan}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          Usage this period
        </h2>
        {usageError || !usage ? (
          <ErrorPanel title="Usage unavailable" message={usageError ?? "No data."} />
        ) : (
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between">
              <dt className="text-neutral-500 dark:text-neutral-400">Analyses used</dt>
              <dd className="font-medium tabular-nums">
                {usage.used.toLocaleString()}
                {usage.limit !== null ? ` / ${usage.limit.toLocaleString()}` : " (unlimited)"}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-neutral-500 dark:text-neutral-400">Period start</dt>
              <dd>{formatDateTime(usage.period_start)}</dd>
            </div>
          </dl>
        )}
      </section>
    </div>
  );
}
