import { redirect } from "next/navigation";

/**
 * Landing route. There is no marketing page yet, so send everyone to the
 * dashboard; the proxy bounces unauthenticated visitors on to /login.
 */
export default function Home() {
  redirect("/dashboard");
}
