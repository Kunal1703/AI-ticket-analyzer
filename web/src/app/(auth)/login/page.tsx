import { LoginForm } from "@/components/LoginForm";
import { sanitizeNextPath } from "@/lib/navigation";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  // Only forward a safe, same-origin next path into the form.
  const safeNext = next ? sanitizeNextPath(next) : null;
  return <LoginForm next={safeNext} />;
}
