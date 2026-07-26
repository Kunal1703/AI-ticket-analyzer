import { SettingsTabs } from "@/components/SettingsTabs";
import { getAuthedContext } from "@/lib/auth/guard";

/**
 * Admin panel shell (M4.5). Requires a signed-in user with an active org
 * (`getAuthedContext` redirects otherwise). Mutations are authorized as
 * owner/admin by the backend; a non-privileged member sees a graceful 403 on
 * the action rather than the controls being hidden (role isn't in the session).
 */
export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  await getAuthedContext();
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <SettingsTabs />
      {children}
    </div>
  );
}
