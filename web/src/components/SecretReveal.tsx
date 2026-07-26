"use client";

import { useState } from "react";

/** One-time reveal of a freshly minted secret, with a copy-to-clipboard button. */
export function SecretReveal({ label, secret }: { label: string; secret: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard?.writeText(secret);
      setCopied(true);
    } catch {
      // clipboard blocked — the value is visible to copy manually
    }
  }

  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950">
      <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
        {label} — copy it now. It won&apos;t be shown again.
      </p>
      <div className="mt-2 flex items-center gap-2">
        <code className="flex-1 overflow-x-auto rounded bg-white px-2 py-1 text-xs dark:bg-neutral-900">
          {secret}
        </code>
        <button
          type="button"
          onClick={copy}
          className="rounded-md border border-neutral-300 px-2 py-1 text-xs font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}
