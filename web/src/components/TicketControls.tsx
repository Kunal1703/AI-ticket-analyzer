"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/SubmitButton";
import { STATUS_LABELS, TICKET_STATUSES } from "@/lib/api/types";
import { updateAssigneeAction, updateStatusAction, type ActionState } from "@/lib/tickets/actions";

const FIELD =
  "h-9 rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";

/** Change a ticket's lifecycle status (PATCH /v1/tickets/{id}). */
export function StatusControl({ ticketId, current }: { ticketId: string; current: string }) {
  const [state, action] = useActionState<ActionState, FormData>(updateStatusAction, {});
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="ticket_id" value={ticketId} />
      <select name="status" defaultValue={current} aria-label="Ticket status" className={FIELD}>
        {TICKET_STATUSES.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
          </option>
        ))}
      </select>
      <SubmitButton pendingLabel="Saving…">Save</SubmitButton>
      {state.error ? (
        <span className="text-xs text-red-600 dark:text-red-400">{state.error}</span>
      ) : null}
      {state.ok ? <span className="text-xs text-green-600 dark:text-green-400">Saved.</span> : null}
    </form>
  );
}

/** Set or clear a ticket's assignee (PATCH /v1/tickets/{id}). */
export function AssigneeControl({
  ticketId,
  current,
}: {
  ticketId: string;
  current: string | null;
}) {
  const [state, action] = useActionState<ActionState, FormData>(updateAssigneeAction, {});
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="ticket_id" value={ticketId} />
      <input
        name="assignee"
        defaultValue={current ?? ""}
        placeholder="Unassigned"
        aria-label="Assignee"
        className={FIELD}
      />
      <SubmitButton pendingLabel="Saving…">Save</SubmitButton>
      {state.error ? (
        <span className="text-xs text-red-600 dark:text-red-400">{state.error}</span>
      ) : null}
      {state.ok ? <span className="text-xs text-green-600 dark:text-green-400">Saved.</span> : null}
    </form>
  );
}
