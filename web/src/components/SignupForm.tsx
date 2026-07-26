"use client";

import Link from "next/link";
import { useActionState } from "react";

import { signupAction, type FormState } from "@/lib/auth/actions";
import { SubmitButton } from "@/components/SubmitButton";

const INPUT =
  "h-10 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm outline-none " +
  "focus:border-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:focus:border-neutral-100";

export function SignupForm() {
  const [state, action] = useActionState<FormState, FormData>(signupAction, {});

  return (
    <form action={action} className="space-y-4 rounded-lg border border-neutral-200 bg-white p-6 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <h2 className="text-lg font-medium">Create your account</h2>

      {state.error ? (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {state.error}
        </p>
      ) : null}

      <div className="space-y-1">
        <label htmlFor="name" className="text-sm font-medium">
          Name <span className="text-neutral-400">(optional)</span>
        </label>
        <input id="name" name="name" type="text" autoComplete="name" className={INPUT} />
      </div>

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
          autoComplete="new-password"
          minLength={8}
          required
          className={INPUT}
        />
        <p className="text-xs text-neutral-500 dark:text-neutral-400">At least 8 characters.</p>
      </div>

      <SubmitButton className="w-full" pendingLabel="Creating account…">
        Sign up
      </SubmitButton>

      <p className="text-center text-sm text-neutral-500 dark:text-neutral-400">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-neutral-900 underline dark:text-neutral-100">
          Log in
        </Link>
      </p>
    </form>
  );
}
