"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/SubmitButton";
import { submitFeedbackAction, type ActionState } from "@/lib/tickets/actions";
import { TICKET_CATEGORIES, TICKET_PRIORITIES } from "@/lib/api/types";

const FIELD =
  "h-9 w-full rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";

/**
 * Records human feedback on the ticket's latest analysis (the training signal):
 * a rating, an optional corrected category/priority, and a comment.
 */
export function FeedbackForm({ ticketId, analysisId }: { ticketId: string; analysisId: string }) {
  const [state, action] = useActionState<ActionState, FormData>(submitFeedbackAction, {});

  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="ticket_id" value={ticketId} />
      <input type="hidden" name="analysis_id" value={analysisId} />

      {state.error ? (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {state.error}
        </p>
      ) : null}
      {state.ok ? (
        <p className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-700 dark:bg-green-950 dark:text-green-300">
          Feedback recorded. Thank you.
        </p>
      ) : null}

      <fieldset className="flex gap-4">
        <legend className="mb-1 text-sm font-medium">Rating</legend>
        <label className="flex items-center gap-1 text-sm">
          <input type="radio" name="rating" value="positive" required /> Positive
        </label>
        <label className="flex items-center gap-1 text-sm">
          <input type="radio" name="rating" value="negative" /> Negative
        </label>
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="font-medium">Corrected category (optional)</span>
          <select name="corrected_category" defaultValue="" className={FIELD}>
            <option value="">— no change —</option>
            {TICKET_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium">Corrected priority (optional)</span>
          <select name="corrected_priority" defaultValue="" className={FIELD}>
            <option value="">— no change —</option>
            {TICKET_PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="space-y-1 text-sm">
        <span className="font-medium">Comment (optional)</span>
        <textarea
          name="comment"
          rows={3}
          maxLength={2000}
          className="w-full rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        />
      </label>

      <SubmitButton pendingLabel="Submitting…">Submit feedback</SubmitButton>
    </form>
  );
}
