"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import type { AdminState } from "@/lib/admin/actions";

function Submit({ label }: { label: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="text-sm font-medium text-red-600 hover:underline disabled:opacity-50 dark:text-red-400"
    >
      {pending ? "…" : label}
    </button>
  );
}

/**
 * A destructive action (revoke/delete) bound to a specific id. The server action
 * reads `id` from the form and returns an `AdminState`; errors show inline.
 */
export function DeleteButton({
  id,
  action,
  label = "Delete",
}: {
  id: string;
  action: (prev: AdminState, formData: FormData) => Promise<AdminState>;
  label?: string;
}) {
  const [state, formAction] = useActionState<AdminState, FormData>(action, {});
  return (
    <form action={formAction} className="inline-flex items-center gap-2">
      <input type="hidden" name="id" value={id} />
      <Submit label={label} />
      {state.error ? (
        <span className="text-xs text-red-600 dark:text-red-400">{state.error}</span>
      ) : null}
    </form>
  );
}
