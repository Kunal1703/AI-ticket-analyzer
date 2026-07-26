import { ApiKeyCreateForm } from "@/components/ApiKeyCreateForm";
import { DeleteButton } from "@/components/DeleteButton";
import { ErrorPanel } from "@/components/ErrorPanel";
import { listApiKeys } from "@/lib/api/admin";
import { ApiError } from "@/lib/api/errors";
import type { ApiKeyResponse } from "@/lib/api/types";
import { revokeApiKeyAction } from "@/lib/admin/actions";
import { getAuthedContext } from "@/lib/auth/guard";

export default async function ApiKeysPage() {
  const { token, orgId } = await getAuthedContext();

  let keys: ApiKeyResponse[] = [];
  let errorMessage: string | null = null;
  try {
    keys = await listApiKeys(token, orgId);
  } catch (error) {
    errorMessage = error instanceof ApiError ? error.message : "Could not load API keys.";
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400">
          Create API key
        </h2>
        <ApiKeyCreateForm />
      </section>

      {errorMessage ? (
        <ErrorPanel title="Couldn't load API keys" message={errorMessage} />
      ) : keys.length === 0 ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">No API keys yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 dark:border-neutral-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-neutral-50 text-xs uppercase text-neutral-500 dark:bg-neutral-900 dark:text-neutral-400">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Prefix</th>
                <th className="px-4 py-2 font-medium">Scopes</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200 dark:divide-neutral-800">
              {keys.map((k) => (
                <tr key={k.id}>
                  <td className="px-4 py-2 font-medium">{k.name}</td>
                  <td className="px-4 py-2 font-mono text-xs text-neutral-500 dark:text-neutral-400">
                    {k.prefix}…
                  </td>
                  <td className="px-4 py-2 text-neutral-600 dark:text-neutral-400">
                    {k.scopes.join(", ")}
                  </td>
                  <td className="px-4 py-2">
                    {k.revoked ? (
                      <span className="text-neutral-400">revoked</span>
                    ) : (
                      <span className="text-green-600 dark:text-green-400">active</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {k.revoked ? null : (
                      <DeleteButton id={k.id} action={revokeApiKeyAction} label="Revoke" />
                    )}
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
