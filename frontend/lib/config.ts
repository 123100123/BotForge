/**
 * Public runtime configuration. NEXT_PUBLIC_* values are inlined at build time, so each must be
 * referenced literally. Mock mode is on only when NEXT_PUBLIC_MOCK=1.
 *
 * Sign-in follows NEXT_PUBLIC_AUTH_PROVIDER, which must name the same provider as the backend's
 * AUTH_PROVIDER:
 * - "local" (the default; the self-hosted Docker stack): the backend's own login. The session is an
 *   HttpOnly cookie, so the backend is reached on the frontend's own origin (Caddy proxies `/api/*` in
 *   production, a Next rewrite does in development) and requests are sent with credentials
 *   "same-origin".
 * - "supabase" (the hosted Render deployment): Supabase Auth in the browser (lib/supabase.ts). Every
 *   request carries the access token as `Authorization: Bearer` and no cookies, so the API may live on
 *   another origin (NEXT_PUBLIC_API_BASE_URL, absolute). Needs NEXT_PUBLIC_SUPABASE_URL and
 *   NEXT_PUBLIC_SUPABASE_ANON_KEY.
 */
const RAW_AUTH_PROVIDER = (process.env.NEXT_PUBLIC_AUTH_PROVIDER ?? "").trim().toLowerCase();
const SUPABASE_URL = (process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").trim();
const SUPABASE_ANON_KEY = (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "").trim();

export type AuthProviderName = "local" | "supabase";

export const AUTH_PROVIDER: AuthProviderName = RAW_AUTH_PROVIDER === "supabase" ? "supabase" : "local";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "/api").replace(/\/+$/, "");

export const IS_MOCK: boolean = process.env.NEXT_PUBLIC_MOCK === "1";

export const SUPABASE_CONFIG = { url: SUPABASE_URL, anonKey: SUPABASE_ANON_KEY };

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** An https URL, or http for a loopback host only (a local Supabase stack): passwords go to this address. */
function isSecureUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || (url.protocol === "http:" && LOOPBACK_HOSTS.has(url.hostname));
  } catch {
    return false;
  }
}

/**
 * Names of required variables that are empty or unusable in real mode (always empty in mock mode); the
 * root layout shows a configuration error naming them instead of the app. The own login needs no
 * build-time variable; Supabase sign-in needs the project's URL and its anon (publishable) key. An
 * unknown NEXT_PUBLIC_AUTH_PROVIDER is an error too, never a silent choice of provider.
 */
export const MISSING_CONFIG: string[] = IS_MOCK
  ? []
  : [
      ...(RAW_AUTH_PROVIDER !== "" && RAW_AUTH_PROVIDER !== "local" && RAW_AUTH_PROVIDER !== "supabase"
        ? ["NEXT_PUBLIC_AUTH_PROVIDER"]
        : []),
      ...(AUTH_PROVIDER === "supabase" && !isSecureUrl(SUPABASE_URL) ? ["NEXT_PUBLIC_SUPABASE_URL"] : []),
      ...(AUTH_PROVIDER === "supabase" && SUPABASE_ANON_KEY === "" ? ["NEXT_PUBLIC_SUPABASE_ANON_KEY"] : []),
    ];
