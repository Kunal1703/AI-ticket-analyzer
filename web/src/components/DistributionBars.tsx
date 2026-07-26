import { barPercent, sortedEntries } from "@/lib/analytics/query";

/**
 * Horizontal magnitude bars for a `{label: count}` distribution, sorted
 * descending. Identity is carried by the row label (not by cycling hues), so
 * bars are a single accent hue by default; a `colorFor` map supplies a
 * meaningful status scale (e.g. priority severity). Values are shown as direct
 * labels in ink — never on the mark color.
 */
export function DistributionBars({
  data,
  colorFor,
}: {
  data: Record<string, number>;
  colorFor?: (label: string) => string;
}) {
  const entries = sortedEntries(data);
  if (entries.length === 0) {
    return (
      <p className="text-sm text-neutral-500 dark:text-neutral-400">No data in this range.</p>
    );
  }
  const max = Math.max(...entries.map(([, v]) => v));

  return (
    <ul className="space-y-2.5">
      {entries.map(([label, value]) => (
        <li key={label}>
          <div className="flex items-center justify-between text-sm">
            <span className="text-neutral-700 dark:text-neutral-300">{label}</span>
            <span className="tabular-nums text-neutral-500 dark:text-neutral-400">{value}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800">
            <div
              className={`h-2 rounded-full ${colorFor?.(label) ?? "bg-sky-500 dark:bg-sky-400"}`}
              style={{ width: `${barPercent(value, max)}%` }}
              aria-hidden
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Severity scale for the priority distribution (a labeled status palette). */
export function priorityBarColor(label: string): string {
  const map: Record<string, string> = {
    Low: "bg-neutral-400 dark:bg-neutral-500",
    Medium: "bg-sky-500 dark:bg-sky-400",
    High: "bg-amber-500 dark:bg-amber-400",
    Critical: "bg-red-500 dark:bg-red-400",
  };
  return map[label] ?? "bg-sky-500 dark:bg-sky-400";
}
