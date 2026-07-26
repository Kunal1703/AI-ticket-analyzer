import { DeleteButton } from "@/components/DeleteButton";
import { ErrorPanel } from "@/components/ErrorPanel";
import { RoutingRuleCreateForm } from "@/components/RoutingRuleCreateForm";
import { SlaPolicyCreateForm } from "@/components/SlaPolicyCreateForm";
import { listRoutingRules, listSlaPolicies } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/errors";
import type { RoutingRuleResponse, SlaPolicyResponse } from "@/lib/api/types";
import { deleteRoutingRuleAction, deleteSlaPolicyAction } from "@/lib/admin/actions";
import { getAuthedContext } from "@/lib/auth/guard";

function describeConditions(conditions: Record<string, string>): string {
  const parts = Object.entries(conditions).map(([k, v]) => `${k}=${v}`);
  return parts.length > 0 ? parts.join(", ") : "any";
}

function describeActions(actions: Record<string, unknown>): string {
  const parts: string[] = [];
  if (typeof actions.assignee === "string" && actions.assignee) {
    parts.push(`assign→${actions.assignee}`);
  }
  if (Array.isArray(actions.tags) && actions.tags.length > 0) {
    parts.push(`tags: ${actions.tags.join(", ")}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "—";
}

export default async function RoutingPage() {
  const { token, orgId } = await getAuthedContext();

  let rules: RoutingRuleResponse[] = [];
  let policies: SlaPolicyResponse[] = [];
  let errorMessage: string | null = null;
  try {
    [rules, policies] = await Promise.all([
      listRoutingRules(token, orgId),
      listSlaPolicies(token, orgId),
    ]);
  } catch (error) {
    errorMessage = error instanceof ApiError ? error.message : "Could not load routing config.";
  }

  if (errorMessage) {
    return <ErrorPanel title="Couldn't load routing configuration" message={errorMessage} />;
  }

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
            Add routing rule
          </h2>
          <RoutingRuleCreateForm />
        </section>

        {rules.length === 0 ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">No routing rules.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-neutral-50 text-xs uppercase text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
                <tr>
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">When</th>
                  <th className="px-4 py-2 font-medium">Then</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td className="px-4 py-2 tabular-nums text-neutral-500">{r.position}</td>
                    <td className="px-4 py-2 font-medium">{r.name}</td>
                    <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                      {describeConditions(r.conditions)}
                    </td>
                    <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                      {describeActions(r.actions)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <DeleteButton id={r.id} action={deleteRoutingRuleAction} label="Delete" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="space-y-4">
        <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
            Add SLA policy
          </h2>
          <SlaPolicyCreateForm />
        </section>

        {policies.length === 0 ? (
          <p className="text-sm text-neutral-500 dark:text-neutral-400">No SLA policies.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
            <table className="w-full text-left text-sm">
              <thead className="bg-neutral-50 text-xs uppercase text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
                <tr>
                  <th className="px-4 py-2 font-medium">Priority</th>
                  <th className="px-4 py-2 font-medium">Resolution (min)</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
                {policies.map((p) => (
                  <tr key={p.id}>
                    <td className="px-4 py-2 font-medium">{p.priority}</td>
                    <td className="px-4 py-2 tabular-nums">{p.resolution_minutes}</td>
                    <td className="px-4 py-2 text-right">
                      <DeleteButton id={p.id} action={deleteSlaPolicyAction} label="Delete" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
