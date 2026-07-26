"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/SubmitButton";
import { CategoryBadge, PriorityBadge } from "@/components/badges";
import { analyzeAction, type AnalyzeState } from "@/lib/tickets/actions";

/**
 * The "AI co-pilot" panel: paste ticket text, get a structured analysis. Submits
 * to `/v1/analyze`, which also persists a ticket under the org (so it appears in
 * the tickets list).
 */
export function AnalyzeForm() {
  const [state, action] = useActionState<AnalyzeState, FormData>(analyzeAction, {});

  return (
    <div className="space-y-6">
      <form action={action} className="space-y-3">
        {state.error ? (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            {state.error}
          </p>
        ) : null}
        <textarea
          name="ticket"
          rows={6}
          required
          maxLength={5000}
          placeholder="Paste the customer's message…"
          className="w-full rounded-md border border-neutral-300 bg-white p-3 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        />
        <SubmitButton pendingLabel="Analyzing…">Analyze</SubmitButton>
      </form>

      {state.result ? (
        <div className="space-y-3 rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
          <div className="flex items-center gap-2">
            <PriorityBadge priority={state.result.priority} />
            <CategoryBadge category={state.result.category} />
          </div>
          <p className="text-sm">{state.result.summary}</p>
          <div>
            <h3 className="text-xs font-semibold uppercase text-neutral-500 dark:text-neutral-400">
              Suggested next actions
            </h3>
            <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm">
              {state.result.next_actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ol>
          </div>
        </div>
      ) : null}
    </div>
  );
}
