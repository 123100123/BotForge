/**
 * Public runtime configuration. NEXT_PUBLIC_* values are inlined at build time, so each must be
 * referenced literally. Mock mode is on only when NEXT_PUBLIC_MOCK=1.
 *
 * The backend is reached on the same origin as the frontend (Caddy proxies `/api/*` in production, a
 * Next rewrite does in development), so the HttpOnly session cookie stays same-origin.
 */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api").replace(/\/+$/, "");

export const IS_MOCK: boolean = process.env.NEXT_PUBLIC_MOCK === "1";
