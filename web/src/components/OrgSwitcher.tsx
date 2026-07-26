import { setActiveOrgAction } from "@/lib/auth/actions";
import type { OrgResponse } from "@/lib/api/types";

/**
 * Lets a multi-org user choose which organization to act as. Submitting sets
 * the active-org cookie (validated server-side against the user's memberships).
 */
export function OrgSwitcher({
  orgs,
  activeOrgId,
}: {
  orgs: OrgResponse[];
  activeOrgId: string | null;
}) {
  return (
    <form action={setActiveOrgAction} className="flex items-center gap-2">
      <select
        name="org_id"
        defaultValue={activeOrgId ?? ""}
        aria-label="Active organization"
        className="h-8 rounded-md border border-neutral-300 bg-white px-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
      >
        {activeOrgId ? null : (
          <option value="" disabled>
            Select organization…
          </option>
        )}
        {orgs.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      <button
        type="submit"
        className="rounded-md border border-neutral-300 px-2 py-1 text-sm transition-colors hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        Switch
      </button>
    </form>
  );
}
