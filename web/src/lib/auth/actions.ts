"use server";

/**
 * Server Actions — the write side of the BFF. These run only on the server, so
 * they are the secure place to exchange credentials for tokens and write the
 * httpOnly session cookies. Each returns a `FormState` for `useActionState`, or
 * redirects on success.
 *
 * `redirect()` works by throwing a control-flow signal, so it is always called
 * *after* the try/catch that talks to the backend — never inside it.
 */

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { createOrg, listOrgs } from "../api/orgs";
import { login, signup } from "../api/auth";
import { ApiError } from "../api/errors";
import { sanitizeNextPath } from "../navigation";
import {
  clearSessionCookies,
  getAccessToken,
  setActiveOrgCookie,
  setSessionCookies,
} from "./cookies";
import { getSession } from "./session";

export interface FormState {
  error?: string;
}

/** Map a backend failure to a concise, user-safe message. */
function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return "Invalid email or password.";
      case 409:
        return "That email is already registered.";
      case 422:
        return "Please check the details you entered.";
      case 503:
        return "The service is temporarily unavailable. Please try again shortly.";
      default:
        return error.message || "Something went wrong. Please try again.";
    }
  }
  return "Something went wrong. Please try again.";
}

/**
 * After issuing tokens, if the user belongs to exactly one org, select it so
 * `X-Organization-Id` is set for subsequent calls. Best-effort — a failure here
 * just leaves the user to pick an org on the dashboard.
 */
async function establishOrgContext(token: string): Promise<void> {
  try {
    const orgs = await listOrgs(token);
    if (orgs.length === 1) await setActiveOrgCookie(orgs[0].id);
  } catch {
    // ignore — org selection is not required to reach the dashboard
  }
}

export async function loginAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const next = sanitizeNextPath(String(formData.get("next") ?? "") || null);
  if (!email || !password) return { error: "Email and password are required." };

  let tokens;
  try {
    tokens = await login(email, password);
  } catch (error) {
    return { error: describeError(error) };
  }
  await setSessionCookies(tokens);
  await establishOrgContext(tokens.access_token);
  redirect(next);
}

export async function signupAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  if (!email || !password) return { error: "Email and password are required." };
  if (password.length < 8) return { error: "Password must be at least 8 characters." };

  let tokens;
  try {
    tokens = await signup(email, password, name || undefined);
  } catch (error) {
    return { error: describeError(error) };
  }
  await setSessionCookies(tokens);
  await establishOrgContext(tokens.access_token);
  redirect("/dashboard");
}

export async function logoutAction(): Promise<void> {
  await clearSessionCookies();
  redirect("/login");
}

export async function createOrgAction(_prev: FormState, formData: FormData): Promise<FormState> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { error: "Organization name is required." };

  const token = await getAccessToken();
  if (!token) redirect("/login");

  let org;
  try {
    org = await createOrg(token, name);
  } catch (error) {
    return { error: describeError(error) };
  }
  await setActiveOrgCookie(org.id);
  revalidatePath("/dashboard");
  redirect("/dashboard");
}

export async function setActiveOrgAction(formData: FormData): Promise<void> {
  const orgId = String(formData.get("org_id") ?? "");
  const session = await getSession();
  // Only allow selecting an org the user actually belongs to.
  if (session && session.orgs.some((o) => o.id === orgId)) {
    await setActiveOrgCookie(orgId);
  }
  revalidatePath("/dashboard");
  redirect("/dashboard");
}
