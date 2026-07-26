"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/SubmitButton";
import type { ActionState } from "@/lib/tickets/actions";

/**
 * A one-click ticket mutation (re-analyze, apply routing). The server action is
 * passed in as a prop, reads `ticket_id` from the form, and returns an
 * `ActionState`; we surface pending / success / error inline.
 */
export function TicketActionButton({
  ticketId,
  action,
  label,
  pendingLabel,
}: {
  ticketId: string;
  action: (prev: ActionState, formData: FormData) => Promise<ActionState>;
  label: string;
  pendingLabel: string;
}) {
  const [state, formAction] = useActionState<ActionState, FormData>(action, {});
  return (
    <form action={formAction} className="flex flex-col gap-1">
      <input type="hidden" name="ticket_id" value={ticketId} />
      <SubmitButton pendingLabel={pendingLabel}>{label}</SubmitButton>
      {state.error ? (
        <span className="text-xs text-red-600 dark:text-red-400">{state.error}</span>
      ) : null}
      {state.ok ? <span className="text-xs text-green-600 dark:text-green-400">Done.</span> : null}
    </form>
  );
}
