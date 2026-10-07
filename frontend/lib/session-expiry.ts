import { IS_MOCK } from "@/lib/config";
import { getSupabase } from "@/lib/supabase";

const LOGIN_PATH = "/login";
const AUTH_PATHS = ["/login", "/signup"];
const DEFAULT_AFTER_LOGIN = "/bots";
const SIGN_OUT_TIMEOUT_MS = 3000;

/** Set once a 401 has started the logout redirect, so concurrent 401s do not start another one. */
let redirecting = false;

function isAuthPath(pathname: string): boolean {
  return AUTH_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

/**
 * `raw` as a same-origin relative path (path, query, hash), or null when it is not one (absolute or
 * protocol-relative URLs, backslashes, control characters) or points at an auth page (would loop).
 */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw || typeof window === "undefined") return null;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\") || /[\u0000-\u001f\u007f]/.test(raw)) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(raw, window.location.origin);
  } catch {
    return null;
  }
  if (url.origin !== window.location.origin || isAuthPath(url.pathname)) return null;
  return url.pathname + url.search + url.hash;
}

/** Where to go after signing in: the validated `?next=` of the current URL, otherwise the bots list. */
export function postLoginPath(): string {
  if (typeof window === "undefined") return DEFAULT_AFTER_LOGIN;
  return safeNextPath(new URLSearchParams(window.location.search).get("next")) ?? DEFAULT_AFTER_LOGIN;
}

/** Drops Supabase's stored session even if `signOut` failed or hung (it would otherwise send the login page back to /bots). */
function removeStoredSession() {
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith("sb-") && key.endsWith("-auth-token")) window.localStorage.removeItem(key);
    }
  } catch {
    /* storage unavailable: nothing was stored there either */
  }
}

/**
 * Our API answered 401 (expired or invalid Supabase session): sign out of Supabase and go to /login,
 * with `?next=` set to the current page. A full navigation (not a router push) drops all in-memory
 * client state. Mock mode never signs out this way.
 */
export async function handleUnauthorized(): Promise<void> {
  if (IS_MOCK || typeof window === "undefined" || redirecting) return;
  redirecting = true;
  const supabase = getSupabase();
  if (supabase) {
    try {
      await Promise.race([
        supabase.auth.signOut({ scope: "local" }),
        new Promise((resolve) => setTimeout(resolve, SIGN_OUT_TIMEOUT_MS)),
      ]);
    } catch {
      /* removed below either way */
    }
  }
  removeStoredSession();
  if (isAuthPath(window.location.pathname)) {
    redirecting = false; // already on an auth page: nothing to leave
    return;
  }
  const next = safeNextPath(window.location.pathname + window.location.search + window.location.hash);
  window.location.replace(next ? `${LOGIN_PATH}?next=${encodeURIComponent(next)}` : LOGIN_PATH);
}
