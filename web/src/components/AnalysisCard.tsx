import { CategoryBadge, PriorityBadge } from "@/components/badges";
import type { AnalysisRead } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

/** One versioned analysis in a ticket's history. */
export function AnalysisCard({ analysis, isLatest }: { analysis: AnalysisRead; isLatest: boolean }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <PriorityBadge priority={analysis.priority} />
        <CategoryBadge category={analysis.category} />
        {isLatest ? (
          <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-950 dark:text-green-300">
            latest
          </span>
        ) : null}
        <span className="ml-auto text-xs text-neutral-500 dark:text-neutral-400">
          {formatDateTime(analysis.created_at)}
          {analysis.model ? ` · ${analysis.model}` : ""}
        </span>
      </div>
      <p className="text-sm">{analysis.summary}</p>
      {analysis.next_actions.length > 0 ? (
        <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-sm text-neutral-700 dark:text-neutral-300">
          {analysis.next_actions.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
