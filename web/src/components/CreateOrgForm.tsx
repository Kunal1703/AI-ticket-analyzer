"use client";

import { useActionState } from "react";

import { createOrgAction, type FormState } from "@/lib/auth/actions";
import { SubmitButton } from "@/components/SubmitButton";

/** First-run form: a user with no organizations creates their first one. */
export function CreateOrgForm() {
  const [state, action] = useActionState<FormState, FormData>(createOrgAction, {});

  return (
    <form action={action} className="space-y-3">
      {state.error ? (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {state.error}
        </p>
      ) : null}
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          name="name"
          type="text"
          required
          placeholder="Acme Support"
          aria-label="Organization name"
          className="h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm outline-none focus:border-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-100"
        />
        <SubmitButton pendingLabel="Creating…">Create organization</SubmitButton>
      </div>
    </form>
  );
}
