import Link from "next/link";

import type { AnalyticsParams } from "@/lib/analytics/query";

const FIELD =
  "h-9 rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";

/** Filters row (metric + date window) above the charts, per interaction spec. */
export function AnalyticsControls({ params }: { params: AnalyticsParams }) {
  const dirty = Boolean(params.start || params.end || params.metric !== "tickets");
  return (
    <form method="get" className="flex flex-wrap items-end gap-3">
      <label className="text-sm">
        <span className="mb-1 block font-medium">Metric</span>
        <select name="metric" defaultValue={params.metric} className={FIELD}>
          <option value="tickets">Tickets</option>
          <option value="analyses">Analyses</option>
        </select>
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">From</span>
        <input type="date" name="start" defaultValue={params.start ?? ""} className={FIELD} />
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">To</span>
        <input type="date" name="end" defaultValue={params.end ?? ""} className={FIELD} />
      </label>
      <button
        type="submit"
        className="h-9 rounded-md border border-neutral-300 px-3 text-sm font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        Apply
      </button>
      {dirty ? (
        <Link href="/analytics" className="text-sm text-neutral-500 underline dark:text-neutral-400">
          Reset
        </Link>
      ) : null}
    </form>
  );
}
