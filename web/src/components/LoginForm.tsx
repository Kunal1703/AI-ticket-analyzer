"use client";

import Link from "next/link";
import { useActionState } from "react";

import { loginAction, type FormState } from "@/lib/auth/actions";
import { SubmitButton } from "@/components/SubmitButton";

const INPUT =
  "h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm outline-none " +
  "focus:border-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-100";

export function LoginForm({ next }: { next: string | null }) {
  const [state, action] = useActionState<FormState, FormData>(loginAction, {});

  return (
    <form action={action} className="space-y-4 rounded-lg border border-neutral-200 bg-white p-6 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <h2 className="text-lg font-medium">Log in</h2>

      {state.error ? (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {state.error}
        </p>
      ) : null}

      {next ? <input type="hidden" name="next" value={next} /> : null}

      <div className="space-y-1">
        <label htmlFor="email" className="text-sm font-medium">
          Email
        </label>
        <input id="email" name="email" type="email" autoComplete="email" required className={INPUT} />
      </div>

      <div className="space-y-1">
        <label htmlFor="password" className="text-sm font-medium">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className={INPUT}
        />
      </div>

      <SubmitButton className="w-full" pendingLabel="Logging in…">
        Log in
      </SubmitButton>

      <p className="text-center text-sm text-neutral-500 dark:text-neutral-400">
        No account?{" "}
        <Link href="/signup" className="font-medium text-neutral-900 underline dark:text-neutral-100">
          Sign up
        </Link>
      </p>
    </form>
  );
}
