/**
 * Layout for the unauthenticated auth pages (login / signup). Centers a card on
 * the page. The proxy keeps already-signed-in users out of this group.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">TriageAI</h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            AI-powered support ticket triage
          </p>
        </div>
        {children}
      </div>
    </div>
  );
}
