"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/SubmitButton";
import { TICKET_PRIORITIES } from "@/lib/api/types";
import { createSlaPolicyAction, type AdminState } from "@/lib/admin/actions";

const FIELD =
  "h-9 w-full rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";

export function SlaPolicyCreateForm() {
  const [state, action] = useActionState<AdminState, FormData>(createSlaPolicyAction, {});
  return (
    <form action={action} className="space-y-3">
      {state.error ? (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {state.error}
        </p>
      ) : null}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="flex-1 text-sm">
          <span className="mb-1 block font-medium">Priority</span>
          <select name="priority" defaultValue="High" className={FIELD}>
            {TICKET_PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="flex-1 text-sm">
          <span className="mb-1 block font-medium">Resolution (minutes)</span>
          <input name="resolution_minutes" type="number" min={1} defaultValue={240} className={FIELD} />
        </label>
        <SubmitButton pendingLabel="Adding…">Add policy</SubmitButton>
      </div>
    </form>
  );
}
