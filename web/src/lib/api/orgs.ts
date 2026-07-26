/**
 * Typed wrappers over the backend organization endpoints (`/v1/orgs`).
 * Server-only.
 */

import "server-only";

import { apiFetch } from "./http";
import type { OrgResponse } from "./types";

export function listOrgs(token: string): Promise<OrgResponse[]> {
  return apiFetch<OrgResponse[]>("/v1/orgs", { token });
}

export function createOrg(token: string, name: string): Promise<OrgResponse> {
  return apiFetch<OrgResponse>("/v1/orgs", {
    method: "POST",
    body: { name },
    token,
  });
}
