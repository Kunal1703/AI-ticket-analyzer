# TriageAI — Web frontend (M4.2)

Next.js 16 (App Router) frontend for the AI Ticket Analyzer backend. This is the
**M4.2 scaffold**: authentication + an application shell. Feature screens
(tickets, analytics) land in later Phase 4 milestones.

It lives in a sibling `web/` directory; the FastAPI backend stays at the repo
root, unchanged.

## Architecture (BFF with httpOnly cookies)

The browser never talks to FastAPI directly. Next.js is a **Backend-for-Frontend**:

- **Server Actions** (`src/lib/auth/actions.ts`) exchange credentials for JWTs
  via the backend and store the access/refresh tokens in **httpOnly cookies** —
  so tokens are never exposed to browser JavaScript (XSS-safe).
- A **server-only session DAL** (`src/lib/auth/session.ts`, `getSession()`)
  reads the access cookie and calls the backend (`/v1/auth/me`, `/v1/orgs`).
- A **Route Handler** (`src/app/api/auth/refresh/route.ts`) renews an expired
  access token using the refresh cookie (Route Handlers can write cookies;
  Server Components cannot).
- The **proxy** (`src/proxy.ts` — Next.js 16's replacement for middleware) does
  optimistic cookie-based redirects (unauthenticated → `/login`, expired access
  → refresh, signed-in → away from `/login`).
- A typed, server-only **API client** (`src/lib/api/*`) mirrors the backend
  schemas and translates the error envelope into `ApiError`.

Because it is a BFF, the backend needs **no CORS/credentials change**: the
browser calls Next.js same-origin, and Next.js calls FastAPI server-to-server.

## Getting started

Requires the backend running (see the repo root README) with `JWT_SECRET` and
`DATABASE_URL` configured, since auth needs both.

```bash
pnpm install
cp .env.example .env.local   # set API_BASE_URL if not http://localhost:8000
pnpm dev                     # http://localhost:3000
```

## Scripts / quality gates

```bash
pnpm lint        # eslint (next config)
pnpm typecheck   # tsc --noEmit
pnpm test        # vitest — unit tests for the pure modules
pnpm build       # production build (also type-checks)
```

## Environment

| Var            | Purpose                                                        |
| -------------- | ------------------------------------------------------------- |
| `API_BASE_URL` | FastAPI base URL as seen from the Next.js server (server-only) |
