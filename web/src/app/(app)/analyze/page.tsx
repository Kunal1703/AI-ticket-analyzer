import { AnalyzeForm } from "@/components/AnalyzeForm";
import { getAuthedContext } from "@/lib/auth/guard";

export default async function AnalyzePage() {
  // Redirects to /login (unauthenticated) or /dashboard (no active org).
  await getAuthedContext();

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New analysis</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Analyze a support message. The result is saved as a ticket under your active
          organization and appears in the tickets list.
        </p>
      </div>
      <AnalyzeForm />
    </div>
  );
}
