"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/SubmitButton";
import { TICKET_CATEGORIES, TICKET_PRIORITIES } from "@/lib/api/types";
import { createRoutingRuleAction, type AdminState } from "@/lib/admin/actions";

const FIELD =
  "h-9 w-full rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";

export function RoutingRuleCreateForm() {
  const [state, action] = useActionState<AdminState, FormData>(createRoutingRuleAction, {});
  return (
    <form action={action} className="space-y-3">
      {state.error ? (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {state.error}
        </p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block font-medium">Name</span>
          <input name="name" required placeholder="Escalate billing" className={FIELD} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Position</span>
          <input name="position" type="number" min={0} defaultValue={0} className={FIELD} />
        </label>
        <div className="hidden lg:block" />
        <label className="text-sm">
          <span className="mb-1 block font-medium">If category</span>
          <select name="condition_category" defaultValue="" className={FIELD}>
            <option value="">any</option>
            {TICKET_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">If priority</span>
          <select name="condition_priority" defaultValue="" className={FIELD}>
            <option value="">any</option>
            {TICKET_PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <div className="hidden lg:block" />
        <label className="text-sm">
          <span className="mb-1 block font-medium">Assign to</span>
          <input name="action_assignee" placeholder="billing-team" className={FIELD} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Tags (comma-separated)</span>
          <input name="action_tags" placeholder="vip, urgent" className={FIELD} />
        </label>
      </div>
      <SubmitButton pendingLabel="Adding…">Add rule</SubmitButton>
    </form>
  );
}
