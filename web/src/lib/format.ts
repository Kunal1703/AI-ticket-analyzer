/**
 * Pure presentation helpers (Next.js-free, unit-tested).
 */

/** Format an ISO timestamp as a compact, locale-stable UTC string. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

/**
 * Describe an SLA deadline relative to now: "overdue" when in the past, else
 * the formatted due time. Returns "—" when there is no deadline.
 */
export function formatSla(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const due = new Date(iso);
  if (Number.isNaN(due.getTime())) return iso;
  if (due.getTime() < now.getTime()) return `overdue (${formatDateTime(iso)})`;
  return formatDateTime(iso);
}

/** Whether an SLA deadline has passed. */
export function isOverdue(iso: string | null | undefined, now: Date = new Date()): boolean {
  if (!iso) return false;
  const due = new Date(iso);
  if (Number.isNaN(due.getTime())) return false;
  return due.getTime() < now.getTime();
}
