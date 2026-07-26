"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/settings", label: "Overview" },
  { href: "/settings/api-keys", label: "API keys" },
  { href: "/settings/webhooks", label: "Webhooks" },
  { href: "/settings/routing", label: "Routing & SLA" },
];

export function SettingsTabs() {
  const path = usePathname();
  return (
    <nav className="flex flex-wrap gap-1 border-b border-neutral-200 dark:border-neutral-800">
      {TABS.map((t) => {
        const active = t.href === "/settings" ? path === "/settings" : path.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            className={
              active
                ? "border-b-2 border-neutral-900 px-3 py-2 text-sm font-medium dark:border-neutral-100"
                : "px-3 py-2 text-sm text-neutral-500 hover:text-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-200"
            }
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
