import { DeleteButton } from "@/components/DeleteButton";
import { ErrorPanel } from "@/components/ErrorPanel";
import { WebhookCreateForm } from "@/components/WebhookCreateForm";
import { listWebhooks } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/errors";
import type { WebhookResponse } from "@/lib/api/types";
import { deleteWebhookAction } from "@/lib/admin/actions";
import { getAuthedContext } from "@/lib/auth/guard";

export default async function WebhooksPage() {
  const { token, orgId } = await getAuthedContext();

  let webhooks: WebhookResponse[] = [];
  let errorMessage: string | null = null;
  try {
    webhooks = await listWebhooks(token, orgId);
  } catch (error) {
    errorMessage = error instanceof ApiError ? error.message : "Could not load webhooks.";
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          Register outbound webhook
        </h2>
        <WebhookCreateForm />
      </section>

      {errorMessage ? (
        <ErrorPanel title="Couldn't load webhooks" message={errorMessage} />
      ) : webhooks.length === 0 ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">No webhooks registered.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-50 text-xs uppercase text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
              <tr>
                <th className="px-4 py-2 font-medium">URL</th>
                <th className="px-4 py-2 font-medium">Events</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {webhooks.map((w) => (
                <tr key={w.id}>
                  <td className="max-w-md truncate px-4 py-2 font-mono text-xs">{w.url}</td>
                  <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                    {w.event_types.join(", ")}
                  </td>
                  <td className="px-4 py-2">
                    {w.active ? (
                      <span className="text-green-600 dark:text-green-400">active</span>
                    ) : (
                      <span className="text-neutral-400">inactive</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <DeleteButton id={w.id} action={deleteWebhookAction} label="Delete" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
