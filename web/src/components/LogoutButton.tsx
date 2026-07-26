import { logoutAction } from "@/lib/auth/actions";

/** Logs the user out by clearing session cookies (a server action). */
export function LogoutButton() {
  return (
    <form action={logoutAction}>
      <button
        type="submit"
        className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium transition-colors hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        Log out
      </button>
    </form>
  );
}
