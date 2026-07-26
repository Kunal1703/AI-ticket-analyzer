/**
 * Server-side configuration for the web BFF.
 *
 * The frontend never talks to FastAPI from the browser. All calls go through
 * the Next.js server (Server Actions / Route Handlers / Server Components),
 * which reads these values. `API_BASE_URL` therefore points at the backend as
 * seen *from the Next.js server* (e.g. http://localhost:8000 in local dev, or a
 * private service URL in production) — it is not exposed to the client.
 */

/** Base URL of the FastAPI backend, as reachable from the Next.js server. */
export const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * Whether cookies should carry the `Secure` attribute. Enabled in production;
 * disabled in development so cookies work over plain http on localhost.
 */
export const COOKIES_SECURE = process.env.NODE_ENV === "production";
