# 22 — Frontend (Next.js BFF)

The frontend lives in a **sibling `web/` directory**; the FastAPI backend at the
repo root is **unchanged** (no moves, no CORS change). Milestones so far:
**M4.2** — the scaffold (auth + app shell); **M4.3** — the agent workspace
(tickets/analyze); **M4.4** — the analytics dashboard; **M4.5** — the admin panel
(`/settings`) — each documented in its own section below. Stack: **Next.js 16
(App Router) + React 19 + TypeScript + Tailwind v4 + pnpm**, with **vitest** for
unit tests.

## The three M4.2 decisions (confirmed with the user)

1. **Sibling `web/` dir**, not a repo restructure — honors the non-breaking
   milestone rule (D19); the backend's `app/`, `alembic/`, Docker, and CI paths
   are untouched. (`.dockerignore` excludes `web/` from the backend image.)
2. **BFF with httpOnly cookies** — the browser never holds tokens; see below.
3. **Auth + app shell scope** — signup/login/logout, token+refresh handling, org
   context, a protected dashboard shell with placeholders. No tickets/analytics
   UI yet.

## Why a BFF (Backend-for-Frontend)

The browser never calls FastAPI directly. Next.js is the BFF: the browser talks
to Next.js **same-origin**, and Next.js talks to FastAPI **server-to-server**.
Consequences:

- **Tokens are `httpOnly` cookies** set by the server and never exposed to
  browser JavaScript (XSS-safe). This is the security win over localStorage.
- **No backend CORS/credentials change** is needed (`cors_allow_credentials`
  stays `False`) — there is no cross-origin browser→FastAPI call.

## Architecture (mirrors the backend's "abstraction + boundary" discipline)

```
Browser ──(same-origin)──▶ Next.js (BFF) ──(Bearer, server-to-server)──▶ FastAPI
   forms/links               Server Actions (write)     /v1/auth/*, /v1/orgs
                             session DAL (read)
                             Route Handler (refresh)
                             proxy (optimistic redirects)
```

- **Server Actions** (`src/lib/auth/actions.ts`, `"use server"`) — the write
  side: `login`/`signup` exchange credentials for JWTs and set the httpOnly
  cookies; `logout` clears them; `createOrg`/`setActiveOrg` manage org context.
  Each returns a `FormState` for `useActionState`, or `redirect()`s on success
  (always **after** the try/catch, since `redirect` throws a control signal).
- **Session DAL** (`src/lib/auth/session.ts`, `server-only`) — `getSession()`
  reads the access cookie, calls `/v1/auth/me` + `/v1/orgs`, resolves the active
  org, and returns `{ user, orgs, activeOrg, token } | null`. Wrapped in React
  `cache` so layout + page + components share **one** backend round-trip. A 401
  (or any error) resolves to `null` (→ login), never throws.
- **Refresh Route Handler** (`src/app/api/auth/refresh/route.ts`) — Route
  Handlers **can** write cookies (Server Components cannot), so this is where an
  expired access token is renewed from the refresh cookie, then redirected back
  to a **sanitized** `next` path (open-redirect guard, `src/lib/navigation.ts`).
- **Proxy** (`src/proxy.ts`) — **Next.js 16 renamed Middleware → Proxy** (same
  functionality). Optimistic, cookie-only (no network): unauthenticated →
  `/login`; refresh-cookie-but-no-access → `/api/auth/refresh`; signed-in →
  away from `/login`/`/signup`. Real enforcement stays in `getSession()`.
- **Typed API client** (`src/lib/api/*`, `server-only`) — one `apiFetch` seam
  attaches `Authorization: Bearer` + optional `X-Organization-Id`, sends/receives
  JSON, and translates the backend error envelope
  (`{"error":{code,message,request_id}}`) into an `ApiError` carrying the HTTP
  status. `types.ts` mirrors the backend Pydantic schemas
  (`TokenResponse`/`UserResponse`/`OrgResponse`).

## Session cookies (`src/lib/auth/cookie-config.ts`)

Three httpOnly cookies: `atk_access`, `atk_refresh`, `atk_org` (active org).
`sameSite=lax`, `path=/`, `secure` in production only (so localhost http works),
and `maxAge` mirroring the backend TTLs (access 900s, refresh 1_209_600s) — so a
browser-dropped access cookie is a reliable "needs refresh" signal the proxy
acts on.

## Org context (multi-tenancy on the frontend)

`getSession()` resolves the active org from the `atk_org` cookie (if the user
still belongs to it), else the sole org, else none. Login/signup auto-select the
org when the user has exactly one. Multi-org users get an `OrgSwitcher` in the
nav (sets `atk_org`, validated server-side against memberships). A user with no
orgs is prompted to create one. The active org id becomes `X-Organization-Id` on
backend calls — matching the backend's JWT tenant-resolution rules ([06_tenancy.md](06_tenancy.md)).

## Routes

| Path | Kind | Notes |
|---|---|---|
| `/` | redirect | → `/dashboard` (proxy bounces unauth to `/login`) |
| `/login`, `/signup` | `(auth)` group | client forms → Server Actions |
| `/dashboard` | `(app)` group | protected shell; `getSession()` or `redirect('/login')` |
| `/api/auth/refresh` | Route Handler | renews tokens, bounces to `next` |

## Next.js 16 specifics (do NOT assume Next 15 knowledge)

The scaffold ships an `AGENTS.md`/`CLAUDE.md` warning that **Next.js 16 has
breaking changes** — read `web/node_modules/next/dist/docs/` before editing.
Key ones this milestone relied on: **`cookies()` is async** (`await cookies()`);
**Middleware is now `proxy.ts`** (`export function proxy` + `export const
config`); route/page **`params`/`searchParams` are Promises**.

## Testing & quality gates

- **Pure modules are Next.js-free** so they unit-test cleanly under vitest:
  error-envelope parsing (`api/errors.ts`), the open-redirect guard
  (`navigation.ts`), cookie option builders (`auth/cookie-config.ts`). 11 tests.
- Gates: `pnpm lint` (eslint), `pnpm typecheck` (`tsc --noEmit`), `pnpm test`
  (vitest), `pnpm build` (also type-checks). A separate **`.github/workflows/
  web-ci.yml`** runs them, path-filtered to `web/**`, independent of the Python
  `CI` workflow.
- **Verified behaviorally** (no backend needed): `/login`/`/signup` render 200;
  `/dashboard` with no cookies → 307 `/login`; with a refresh-only cookie → 307
  `/api/auth/refresh`; `/` → 307 `/dashboard`. A real login round-trip needs a
  live Postgres+`JWT_SECRET` backend (not available in this env, per [15_handoff.md](15_handoff.md)).

## What must NEVER change

- Tokens live **only** in httpOnly cookies, set **server-side**; never exposed to
  browser JS, never in localStorage.
- The BFF boundary: browser→Next same-origin, Next→FastAPI server-side. Don't add
  a direct browser→FastAPI call (it would reintroduce CORS + token exposure).
- The backend stays **unchanged** by frontend work (no CORS/credentials edits,
  no schema changes); `web/` is excluded from the backend Docker image.
- Pure modules (`errors`, `navigation`, `cookie-config`) stay **Next.js-free** so
  they remain unit-testable; server-only modules keep `import "server-only"`.
- `redirect()` is called outside try/catch (it throws a control signal).

## M4.2 deferred / next

- **✅ M4.3** agent workspace + AI co-pilot panel — **done** (see the M4.3
  section below).
- **M4.4** manager dashboard + analytics UI (consumes `/v1/analytics/*`).
- Generated TypeScript types from the backend OpenAPI schema (replacing the
  hand-written `types.ts` as the surface grows).
- Component/e2e tests (React Testing Library / Playwright) once there is
  interactive feature surface; M4.2 covers the pure logic only.
- Honor `next` after refresh in more flows; richer error surfaces; a real
  marketing landing page.

---

# M4.3 — Agent workspace (read-first, existing API only)

Implemented in **M4.3**. **Constraint (from the user): use the existing API
only — no backend endpoints added.** The workspace was built as far as the
current backend allows; every missing endpoint hit during implementation is
recorded below as **follow-up tech debt** instead of extending the backend
mid-milestone. Whether a small backend "ticket lifecycle/status" milestone is
warranted is decided *after* M4.3.

## What it adds

Three screens under the `(app)` group, all reusing the M4.2 BFF seams (typed
server-only API client + `getSession()`), guarded by `getAuthedContext()` (which
requires a signed-in user **with an active org**, else redirects to
`/login`/`/dashboard`):

| Route | Backing endpoint(s) | Purpose |
|---|---|---|
| `/tickets` | `GET /v1/tickets` | Paginated list + category/priority filters; latest analysis, assignee, SLA (overdue flagged) per row |
| `/tickets/[id]` | `GET /v1/tickets/{id}`, `.../feedback` | Original text, full versioned analysis history, feedback list |
| `/analyze` | `POST /v1/analyze` | AI co-pilot: paste a message → structured analysis (also persists a ticket) |

**Mutations (Server Actions, `web/src/lib/tickets/actions.ts`):** re-analyze
(`POST /v1/tickets/{id}/reanalyze`), apply routing/SLA (`POST /v1/tickets/{id}/
route`), submit feedback (`POST /v1/tickets/{id}/feedback`), ad-hoc analyze
(`POST /v1/analyze`). Each resolves the tenant context, calls the backend, maps
the error envelope to a user-safe message (402 quota, 409 no-analysis, etc.), and
`revalidatePath`s the affected pages.

## Structure / conventions (unchanged from M4.2)

- **Reads in Server Components** (pages call the API client with `token` +
  `orgId`), wrapped in try/catch → an `ErrorPanel` on failure (so a down backend
  degrades gracefully instead of crashing the page).
- **Mutations via Server Actions + `useActionState`** client components
  (`TicketActionButton`, `FeedbackForm`, `AnalyzeForm`) — pending/error/success
  inline. Server actions are passed as props from server pages to client buttons.
- **Pure, Next-free, unit-tested helpers:** `lib/tickets/query.ts` (param
  parse/clamp/serialize — validates `category`/`priority` against the fixed
  enums, clamps `limit` 1–100 / `offset` ≥ 0) and `lib/format.ts` (date/SLA
  formatting, overdue). +12 vitest tests (23 total).
- **Proxy** now also protects `/tickets` and `/analyze`.

## Verified

`pnpm lint` / `typecheck` / `test` (23) / `build` all green. Behavioral smoke
(no backend needed): `/tickets`, `/tickets/{id}`, `/analyze` unauthenticated →
307 `/login?next=…`; refresh-only cookie → 307 `/api/auth/refresh`. Authenticated
data flows need a live Postgres+`JWT_SECRET` backend (unavailable in this env),
but the pages fail soft via `ErrorPanel`.

## Backend gaps found during M4.3 → **RESOLVED by M3.6**

M4.3's read/triage workspace was fully functional, but a *complete* agent
workspace needed backend surface that didn't exist. These were recorded as tech
debt and then closed by the **M3.6** backend milestone (see [17_tickets.md](17_tickets.md)):

1. ~~No ticket status/lifecycle~~ → **✅ `tickets.status` (`open`/`in_progress`/
   `pending`/`resolved`/`closed`) + `PATCH /v1/tickets/{id}`.**
2. ~~No manual assignment~~ → **✅ `PATCH /v1/tickets/{id}` updates `assignee`**
   (any member; `{"assignee": null}` clears).
3. ~~Limited list querying~~ → **✅ `GET /v1/tickets` gains `status`/`assignee`/
   `source`/`search` filters + `sort`** (created_at asc/desc). Cursor pagination
   still deferred.
4. ~~Analyze/reanalyze don't return the ticket id~~ → **✅ `AnalyzeResponse`
   (`TicketAnalysis` + `ticket_id`)** on `/v1/analyze` + `/reanalyze`.

**Still deferred (out of M3.6 scope):**
5. **No ticket delete** (`DELETE /v1/tickets/{id}`) for GDPR/cleanup.
6. **No bulk actions** (multi-select route/assign/close).
7. **No SLA breach/escalation state** — SLA is a due timestamp only; "overdue" is
   computed client-side; there's no breach flag or escalation.

> **✅ Frontend integration complete.** The M4.3 workspace now **consumes** the
> full M3.6 surface — see the "M3.6 frontend integration" section below.

---

# M3.6 frontend integration (completes the M4.3 workspace)

Wiring the M3.6 backend surface into the existing agent workspace — **not a new
milestone**, the completion of M4.3 using APIs that already shipped. Frontend-only,
no backend changes, existing BFF patterns.

## What it wires

- **Ticket status controls** — a status `<select>` (`open`/`in_progress`/
  `pending`/`resolved`/`closed`) + Save on the ticket detail page, via
  `updateStatusAction` → `PATCH /v1/tickets/{id}` (`StatusControl`). A
  `StatusBadge` shows status in the header and as a **new column** in the list.
- **Manual assignee editing** — an assignee input + Save (`AssigneeControl` →
  `updateAssigneeAction` → `PATCH`); an empty value sends `{"assignee": null}` to
  clear, a value sets it (backend `model_fields_set` semantics).
- **New list filters + sort** — `status`, `source`, `assignee`, `search`, and
  `sort` (newest/oldest) added to the `/tickets` GET‑form filter row; parsed/
  validated in `lib/tickets/query.ts` (enums checked, free‑text trimmed) and
  threaded through `listTickets` + pagination links. A `hasActiveFilters` helper
  drives the Clear link.
- **`ticket_id` deep-linking** — `analyzeText`/`reanalyzeTicket` now return
  `AnalyzeResponse` (`+ ticket_id`); `analyzeAction` **redirects to
  `/tickets/{ticket_id}`** after a successful co‑pilot analysis (falls back to the
  inline result when no DB). Re‑analyze already sits on the ticket, so it just
  revalidates.

## Files

`web/src/lib/api/types.ts` (`TICKET_STATUSES`/`STATUS_LABELS`/`TICKET_SOURCES`/
`TICKET_SORTS`, `AnalyzeResponse`, `UpdateTicketBody`, `status` on ticket models);
`web/src/lib/api/tickets.ts` (`updateTicket`, filter params, `AnalyzeResponse`
returns); `web/src/lib/tickets/{query,actions}.ts` (filters + `updateStatusAction`/
`updateAssigneeAction` + deep‑link); `web/src/components/{badges,TicketControls}.tsx`;
the `/tickets` + `/tickets/[id]` pages. **Backend untouched.**

## Verified

`pnpm lint` / `typecheck` / `test` (**41**, +3 for the extended filter parsing) /
`build` all green. Smoke (no backend): `/tickets` with the new filter params +
`/tickets/{id}` still route/redirect correctly; live PATCH/deep‑link needs a
Postgres+`JWT_SECRET` backend (unavailable here). This closes the M4.3 →
"RESOLVED by M3.6" follow‑up above.

## M4.3 deferred / next

- Per-analysis-version feedback UI (the API already accepts `analysis_id`; M4.3
  posts feedback on the latest analysis only).
- Component/e2e tests (Playwright) now that there is interactive surface.

---

# M4.4 — Analytics dashboard

Implemented in **M4.4**. A tenant-scoped analytics dashboard consuming the M4.1
API (`/v1/analytics/{summary,timeseries}`), reusing the M4.2 BFF seams. **Scope
(confirmed with the user): the analytics UI only** — the admin panel (API keys /
webhooks / routing-config UI, all already API-backed) is deferred to a later
milestone to keep this reviewable.

## What it adds

- **`/analytics`** (`(app)` group, guarded by `getAuthedContext`): stat tiles
  (total tickets / analyses), a daily **timeseries** bar chart (metric = tickets
  or analyses), and **by-priority / by-category** distribution bars. A filters row
  (metric + date window) is a server-rendered **GET form** — no client JS.
- **Server-only API client** `web/src/lib/api/analytics.ts` (`getSummary`/
  `getTimeseries`) + analytics types mirroring `app/models.py`. Reads happen in a
  Server Component (parallel `Promise.all`), fail-soft via `ErrorPanel`.
- **Pure, unit-tested helpers** `web/src/lib/analytics/query.ts`: param
  parse/validate (ISO date, metric enum), href builder, `barPercent` scaling,
  `sortedEntries`. +10 vitest tests (33 total).
- Nav gains an **Analytics** link; the dashboard's Analytics card is now live;
  the proxy protects `/analytics`.

## Charting (native, no dependency)

Charts are hand-rolled (CSS bars + one small SVG), **no charting library**,
applying the dataviz method to the app's existing Tailwind design:

- **Category distribution** — single-hue horizontal bars sorted desc; identity is
  carried by the row **label**, not by cycling 8 hues (avoids the categorical-
  rainbow anti-pattern).
- **Priority distribution** — the existing **severity color scale**
  (Low→neutral, Medium→sky, High→amber, Critical→red), a *labeled* status
  palette (never color-alone).
- **Timeseries** — a single-hue SVG bar chart with a recessive baseline and a
  per-bar hover `<title>` (date + count); the peak is called out in the caption
  rather than printing a value on every bar.
- Values/labels stay in ink (text tokens), never on the mark color; theme-aware
  (light/dark); one measure per chart (no dual axis).

## What must NEVER change

- Analytics stays **read-only + tenant-scoped** through the BFF (bearer +
  `X-Organization-Id`); reads fail soft (never crash the page).
- Charts stay dependency-light and consistent with the app design; one measure
  per chart; identity by label/legend, not hue-cycling.

## Verified

`pnpm lint` / `typecheck` / `test` (33) / `build` all green. Smoke (no backend):
`/analytics` unauthenticated → 307 `/login?next=/analytics`; refresh-only cookie →
307 `/api/auth/refresh`. A visual pass against **real** aggregates needs a live
Postgres+`JWT_SECRET` backend (unavailable here); the page fail-softs to
`ErrorPanel`, and the bar-scaling math is unit-tested.

## M4.4 deferred / next

- Latest-analysis-per-ticket distributions, cost/usage analytics, assignee/routing
  breakdowns (need the deferred backend analytics from [21_analytics.md](21_analytics.md)).
- Component/e2e tests (Playwright); a hover tooltip layer richer than `<title>`.

---

# M4.5 — Admin panel (`/settings`)

Implemented in **M4.5**. A tenant-scoped admin panel over the existing org-scoped
endpoints (API keys, webhooks, routing rules, SLA policies, usage), reusing the
BFF seams. **Backend untouched.**

## What it adds

A `/settings` area (`(app)` group, `getAuthedContext` guard) with a tab sub-nav
(`SettingsTabs`, client, `usePathname` for the active tab):

| Route | Endpoints | Purpose |
|---|---|---|
| `/settings` | `GET /v1/orgs/{id}/usage` | Org (name/slug/plan) + usage/limit/period |
| `/settings/api-keys` | `…/api-keys` (POST/GET/DELETE) | List + create (secret once) + revoke |
| `/settings/webhooks` | `…/webhooks` (POST/GET/DELETE) | List + create (signing secret once) + delete |
| `/settings/routing` | `…/routing-rules` + `…/sla-policies` | List + create + delete for both |

- **Server-only client** `web/src/lib/api/admin.ts` + admin types mirroring
  `app/models.py`. These routes take `org_id` in the **path** and authorize via
  the user JWT (`require_org_membership`/`require_role`), so the client passes the
  bearer token and puts the org id in the URL (no `X-Organization-Id` header).
- **Server Actions** `web/src/lib/admin/actions.ts` — create/revoke/delete for
  each resource; each resolves the authed org, calls the endpoint, maps errors
  (esp. **403 → "owner or admin required"**), and `revalidatePath`s. **Create
  actions that mint a one-time secret return it in the action state** (revealed
  once via `SecretReveal`, with copy) rather than redirecting.
- **Pure, unit-tested helpers** `web/src/lib/admin/parse.ts` (`parseCsvList` for
  scopes/tags/event-types; `buildRoutingConditions`/`buildRoutingActions`) — +5
  vitest tests (38 total).
- Components: `SecretReveal`, a generic `DeleteButton` (id + bound action), and
  per-resource create forms (`ApiKeyCreateForm`/`WebhookCreateForm`/
  `RoutingRuleCreateForm`/`SlaPolicyCreateForm`). Nav gains a **Settings** link;
  the proxy protects `/settings`.

## Authorization note (role is not in the session)

The backend enforces **owner/admin** on mutations; a non-privileged member gets a
graceful **403** surfaced inline. The UI does **not** role-hide the controls,
because the session has no role field (no endpoint returns the caller's role in an
org). Surfacing role in the session (to hide controls) is a small backend
follow-up, kept out of M4.5 to stay backend-untouched.

## What must NEVER change

- Admin routes stay org-scoped through the BFF (bearer + path `org_id`); the
  backend remains the authorization gate (never rely on UI hiding).
- One-time secrets (API key plaintext, webhook signing secret) are shown **once**
  from the action state and never re-fetched.

## Verified

`pnpm lint` / `typecheck` / `test` (38) / `build` all green. Smoke (no backend):
`/settings` + sub-pages unauthenticated → 307 `/login?next=…`; refresh-only cookie
→ 307 `/api/auth/refresh`. Live CRUD needs a Postgres+`JWT_SECRET` backend
(unavailable here); pages fail-soft via `ErrorPanel`.

## Deferred / next

- Surface the caller's **role** in the session to role-hide controls (small
  backend follow-up); webhook enable/disable + secret rotation, routing‑rule
  edit, deliveries log (need backend endpoints).
- ~~The M3.6 frontend follow-up~~ → **✅ done** (see "M3.6 frontend integration").
- Component/e2e tests (Playwright).
