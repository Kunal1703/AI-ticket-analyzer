"use client";

import { useActionState } from "react";

import { SecretReveal } from "@/components/SecretReveal";
import { SubmitButton } from "@/components/SubmitButton";
import { createWebhookAction, type SecretState } from "@/lib/admin/actions";

const INPUT =
  "h-9 w-full rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900";

export function WebhookCreateForm() {
  const [state, action] = useActionState<SecretState, FormData>(createWebhookAction, {});
  return (
    <form action={action} className="space-y-3">
      {state.error ? (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {state.error}
        </p>
      ) : null}
      {state.secret ? <SecretReveal label="Signing secret" secret={state.secret} /> : null}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="flex-1 text-sm">
          <span className="mb-1 block font-medium">Endpoint URL</span>
          <input
            name="url"
            type="url"
            required
            placeholder="https://example.com/hooks/triage"
            className={INPUT}
          />
        </label>
        <label className="flex-1 text-sm">
          <span className="mb-1 block font-medium">Event types</span>
          <input name="event_types" defaultValue="batch.completed" className={INPUT} />
        </label>
        <SubmitButton pendingLabel="Registering…">Add webhook</SubmitButton>
      </div>
    </form>
  );
}
