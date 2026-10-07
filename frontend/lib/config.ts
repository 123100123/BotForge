/**
 * Public runtime configuration. NEXT_PUBLIC_* values are inlined at build time, so each must be
 * referenced literally. Mock mode is on only when NEXT_PUBLIC_MOCK=1.
 *
 * The backend is reached on the same origin as the frontend (Caddy proxies `/api/*` in production, a
 * Next rewrite does in development), so the HttpOnly session cookie stays same-origin.
 */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api").replace(/\/+$/, "");

export const IS_MOCK: boolean = process.env.NEXT_PUBLIC_MOCK === "1";

/**
 * Names of required variables that are empty in real mode (always empty in mock mode); the root layout
 * shows a configuration error naming them instead of the app. The own login (session cookie) needs no
 * build-time variable, so the list is empty; a token-based auth provider adds its variables here.
 */
export const MISSING_CONFIG: string[] = [];
