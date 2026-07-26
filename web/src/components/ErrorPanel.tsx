/** Inline error state for a Server Component whose backend fetch failed. */
export function ErrorPanel({ title, message }: { title: string; message: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
    >
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-red-700 dark:text-red-400">{message}</p>
    </div>
  );
}
