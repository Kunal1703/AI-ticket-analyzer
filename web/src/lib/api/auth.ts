/**
 * Typed wrappers over the backend auth endpoints (`/v1/auth/*`). Server-only.
 */

import "server-only";

import { apiFetch } from "./http";
import type { TokenResponse, UserResponse } from "./types";

export function signup(email: string, password: string, name?: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/v1/auth/signup", {
    method: "POST",
    body: { email, password, ...(name ? { name } : {}) },
  });
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/v1/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export function refresh(refreshToken: string): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/v1/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export function me(token: string): Promise<UserResponse> {
  return apiFetch<UserResponse>("/v1/auth/me", { token });
}
