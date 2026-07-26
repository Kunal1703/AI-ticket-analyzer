/** Small colored labels for ticket priority/category/status. Server components. */

import { STATUS_LABELS, type TicketStatus } from "@/lib/api/types";

const PRIORITY_STYLES: Record<string, string> = {
  Low: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  Medium: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  High: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  Critical: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

const STATUS_STYLES: Record<string, string> = {
  open: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  in_progress: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  pending: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  resolved: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  closed: "bg-neutral-200 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400",
};

const BADGE_BASE = "inline-block rounded-full px-2 py-0.5 text-xs font-medium";

export function StatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-xs text-neutral-400">—</span>;
  const label = STATUS_LABELS[status as TicketStatus] ?? status;
  const style =
    STATUS_STYLES[status] ??
    "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";
  return <span className={`${BADGE_BASE} ${style}`}>{label}</span>;
}

export function PriorityBadge({ priority }: { priority: string | null }) {
  if (!priority) return <span className="text-xs text-neutral-400">—</span>;
  const style =
    PRIORITY_STYLES[priority] ??
    "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";
  return <span className={`${BADGE_BASE} ${style}`}>{priority}</span>;
}

export function CategoryBadge({ category }: { category: string | null }) {
  if (!category) return <span className="text-xs text-neutral-400">—</span>;
  return (
    <span
      className={`${BADGE_BASE} bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300`}
    >
      {category}
    </span>
  );
}
