import Link from "next/link";

import { CategoryBadge, PriorityBadge, StatusBadge } from "@/components/badges";
import { ErrorPanel } from "@/components/ErrorPanel";
import { listTickets } from "@/lib/api/tickets";
import { ApiError } from "@/lib/api/errors";
import {
  STATUS_LABELS,
  TICKET_CATEGORIES,
  TICKET_PRIORITIES,
  TICKET_SORTS,
  TICKET_SOURCES,
  TICKET_STATUSES,
} from "@/lib/api/types";
import type { PaginatedTickets } from "@/lib/api/types";
import { getAuthedContext } from "@/lib/auth/guard";
import { formatDateTime, formatSla, isOverdue } from "@/lib/format";
import { buildTicketsHref, hasActiveFilters, parseTicketListParams } from "@/lib/tickets/query";

const SELECT =
  "h-9 rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";

export default async function TicketsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = parseTicketListParams(await searchParams);
  const { token, orgId } = await getAuthedContext();

  let page: PaginatedTickets | null = null;
  let errorMessage: string | null = null;
  try {
    page = await listTickets(token, orgId, params);
  } catch (error) {
    errorMessage =
      error instanceof ApiError
        ? error.message
        : "Could not load tickets. Is the backend running?";
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Tickets</h1>
        <Link
          href="/analyze"
          className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-white dark:text-neutral-900"
        >
          New analysis
        </Link>
      </div>

      <form method="get" className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block font-medium">Status</span>
          <select name="status" defaultValue={params.status ?? ""} className={SELECT}>
            <option value="">All</option>
            {TICKET_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Category</span>
          <select name="category" defaultValue={params.category ?? ""} className={SELECT}>
            <option value="">All</option>
            {TICKET_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Priority</span>
          <select name="priority" defaultValue={params.priority ?? ""} className={SELECT}>
            <option value="">All</option>
            {TICKET_PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Source</span>
          <select name="source" defaultValue={params.source ?? ""} className={SELECT}>
            <option value="">All</option>
            {TICKET_SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Assignee</span>
          <input
            name="assignee"
            defaultValue={params.assignee ?? ""}
            placeholder="anyone"
            className={SELECT}
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Search</span>
          <input
            name="search"
            defaultValue={params.search ?? ""}
            placeholder="ticket text…"
            className={SELECT}
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Sort</span>
          <select name="sort" defaultValue={params.sort} className={SELECT}>
            {TICKET_SORTS.map((s) => (
              <option key={s} value={s}>
                {s === "-created_at" ? "Newest first" : "Oldest first"}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          className="h-9 rounded-md border border-neutral-300 px-3 text-sm font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          Apply
        </button>
        {hasActiveFilters(params) ? (
          <Link href="/tickets" className="text-sm text-neutral-500 underline dark:text-neutral-400">
            Clear
          </Link>
        ) : null}
      </form>

      {errorMessage ? (
        <ErrorPanel title="Couldn't load tickets" message={errorMessage} />
      ) : page && page.items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-neutral-300 p-8 text-center text-sm text-neutral-500 dark:border-neutral-700 dark:text-neutral-400">
          No tickets yet. Run a{" "}
          <Link href="/analyze" className="underline">
            new analysis
          </Link>{" "}
          to create one.
        </p>
      ) : page ? (
        <>
          <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-neutral-50 text-xs uppercase text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
                <tr>
                  <th className="px-4 py-2 font-medium">Summary</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Priority</th>
                  <th className="px-4 py-2 font-medium">Category</th>
                  <th className="px-4 py-2 font-medium">Assignee</th>
                  <th className="px-4 py-2 font-medium">SLA</th>
                  <th className="px-4 py-2 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {page.items.map((t) => (
                  <tr key={t.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-900">
                    <td className="max-w-md px-4 py-2">
                      <Link href={`/tickets/${t.id}`} className="font-medium underline-offset-2 hover:underline">
                        {t.latest_summary ?? "(no analysis)"}
                      </Link>
                      <span className="ml-2 text-xs text-neutral-400">
                        {t.source} · {t.analyses_count} rev
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="px-4 py-2">
                      <PriorityBadge priority={t.latest_priority} />
                    </td>
                    <td className="px-4 py-2">
                      <CategoryBadge category={t.latest_category} />
                    </td>
                    <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                      {t.assignee ?? "—"}
                    </td>
                    <td
                      className={`px-4 py-2 ${isOverdue(t.sla_due_at) ? "text-red-600 dark:text-red-400" : "text-neutral-600 dark:text-neutral-400"}`}
                    >
                      {formatSla(t.sla_due_at)}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-neutral-600 dark:text-neutral-400">
                      {formatDateTime(t.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-sm text-neutral-500 dark:text-neutral-400">
            <span>
              {page.total === 0
                ? "0 tickets"
                : `${page.offset + 1}–${Math.min(page.offset + page.limit, page.total)} of ${page.total}`}
            </span>
            <div className="flex gap-2">
              {page.offset > 0 ? (
                <Link
                  href={buildTicketsHref({
                    ...params,
                    offset: Math.max(0, page.offset - page.limit),
                  })}
                  className="rounded-md border border-neutral-300 px-3 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
                >
                  ← Prev
                </Link>
              ) : null}
              {page.offset + page.limit < page.total ? (
                <Link
                  href={buildTicketsHref({ ...params, offset: page.offset + page.limit })}
                  className="rounded-md border border-neutral-300 px-3 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
                >
                  Next →
                </Link>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
