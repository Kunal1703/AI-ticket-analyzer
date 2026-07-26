"use client";

import { useFormStatus } from "react-dom";

/**
 * Submit button that disables itself and shows a pending label while the
 * enclosing form's action is in flight. Must be rendered inside a `<form>`.
 */
export function SubmitButton({
  children,
  pendingLabel = "Please wait…",
  className = "",
}: {
  children: React.ReactNode;
  pendingLabel?: string;
  className?: string;
}) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className={
        "inline-flex h-10 items-center justify-center rounded-md bg-neutral-900 px-4 text-sm font-medium " +
        "text-white transition-colors hover:bg-neutral-700 disabled:cursor-not-allowed disabled:opacity-60 " +
        "dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200 " +
        className
      }
    >
      {pending ? pendingLabel : children}
    </button>
  );
}
