import { AUTH_PROVIDER, IS_MOCK } from "@/lib/config";
import { signOutOfSupabase } from "@/lib/supabase";

/**
 * What happens when the backend answers 401, and where the user goes after signing in (`?next=`).
 * Used with both sign-in providers (lib/config.ts). Checked by scripts/check-next-path.mjs.
 */

const LOGIN_PATH = "/login";
const AUTH_PATHS = ["/login", "/signup"];
const DEFAULT_AFTER_LOGIN = "/bots";
const MAX_NEXT_LENGTH = 2048;
const MAX_DECODE_ROUNDS = 3;

/**
 * Window event fired when the session ends while the user stays on an auth page. The AuthProvider
 * listens and drops to the signed-out state. Elsewhere `handleUnauthorized` navigates to the login
 * page instead.
 */
export const UNAUTHORIZED_EVENT = "botforge:unauthorized";

// Printable ASCII without the space: what an address bar holds for this app's own paths (the browser
// percent-encodes everything else). Anything else in `next` is refused before it is parsed.
const PRINTABLE_ASCII = /^[\x21-\x7e]+$/;
// A C0 control character or DEL (URL parsers drop tabs and line breaks, which turns "/\t/host" into
// "//host"), or a backslash (parsers read it as "/", so "/\host" is "//host").
const UNSAFE_CHARACTER = /[\u0000-\u001f\u007f\\]/;
const SCRIPT_SCHEME = /(?:java|vb)script:/i;

/** Set once a 401 has started the redirect to the login page, so concurrent 401s do not start another. */
let redirecting = false;

export function isAuthPath(pathname: string): boolean {
  return AUTH_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

function currentOrigin(): string | null {
  return typeof window === "undefined" ? null : window.location.origin;
}

/**
 * `value` and every string that percent-decoding it can produce, or null when decoding fails
 * (malformed) or still changes it after MAX_DECODE_ROUNDS rounds (nothing this app links to is
 * encoded more than twice).
 */
function decodedForms(value: string): string[] | null {
  const forms = [value];
  for (let round = 0; round < MAX_DECODE_ROUNDS; round++) {
    const last = forms[forms.length - 1];
    let decoded: string;
    try {
      decoded = decodeURIComponent(last);
    } catch {
      return null;
    }
    if (decoded === last) return forms;
    forms.push(decoded);
  }
  return null;
}

/**
 * Whether no decoding of `path` can lead away from `origin`: each form starts with one "/", holds no
 * backslash, control character or script scheme, and resolves to a URL on `origin` whose path does
 * not start with "//".
 */
function staysOnOrigin(path: string, origin: string): boolean {
  const forms = decodedForms(path);
  if (forms === null) return false;
  return forms.every((form) => {
    if (!form.startsWith("/") || form.startsWith("//") || UNSAFE_CHARACTER.test(form) || SCRIPT_SCHEME.test(form)) {
      return false;
    }
    try {
      const url = new URL(form, origin);
      return url.origin === origin && !url.pathname.startsWith("//");
    } catch {
      return false;
    }
  });
}

/**
 * SECURITY: `raw` (normally the login page's `?next=`) as a same-origin relative path (path, query,
 * hash) to navigate to after signing in, or null. Anyone can send a link to the login page with any
 * `next`, and the result goes to `router.replace`, so an accepted absolute or protocol-relative URL
 * would be an open redirect (or script execution, for `javascript:`).
 *
 * Accepted: printable ASCII of at most MAX_NEXT_LENGTH characters that starts with a single "/".
 * Refused: "//host", "/\host" and backslashes anywhere, absolute URLs ("https://", "javascript:"),
 * control characters, the percent-encoded forms of all of these, dot segments that the URL parser
 * turns into "//host" ("/..//host", "/%2e%2e//host"), and the login and signup pages (a loop). The
 * value returned is the URL parser's normalized form, checked the same way again.
 */
export function safeNextPath(raw: string | null | undefined, origin: string | null = currentOrigin()): string | null {
  if (typeof raw !== "string" || !origin || raw.length > MAX_NEXT_LENGTH || !PRINTABLE_ASCII.test(raw)) {
    return null;
  }
  if (!staysOnOrigin(raw, origin)) return null;
  let url: URL;
  try {
    url = new URL(raw, origin);
  } catch {
    return null;
  }
  const path = url.pathname + url.search + url.hash;
  if (url.origin !== origin || isAuthPath(url.pathname) || !staysOnOrigin(path, origin)) return null;
  return path;
}

/** Where to go after signing in: the validated `?next=` of `search` (the current URL's), otherwise the bots list. */
export function postLoginPath(
  search: string = typeof window === "undefined" ? "" : window.location.search,
  origin: string | null = currentOrigin(),
): string {
  return safeNextPath(new URLSearchParams(search).get("next"), origin) ?? DEFAULT_AFTER_LOGIN;
}

/** The login page, with `?next=` set to `current` (the current page) when that is a safe target. */
export function loginRedirectPath(
  current: string = typeof window === "undefined"
    ? ""
    : window.location.pathname + window.location.search + window.location.hash,
  origin: string | null = currentOrigin(),
): string {
  const next = safeNextPath(current, origin);
  return next ? `${LOGIN_PATH}?next=${encodeURIComponent(next)}` : LOGIN_PATH;
}

/**
 * The backend answered 401: the session expired or was revoked, or the token is not accepted. With
 * Supabase sign-in, sign out of Supabase first (otherwise the login page would send the user straight
 * back with the dead session). Then, with either provider, go to the login page with `?next=` set to
 * the current page; a full navigation (not a router push) drops all in-memory client state. On an auth
 * page there is nothing to leave: the AuthProvider just drops to signed-out. Mock mode never signs out
 * this way.
 */
export async function handleUnauthorized(): Promise<void> {
  if (IS_MOCK || typeof window === "undefined" || redirecting) return;
  redirecting = true;
  if (AUTH_PROVIDER === "supabase") await signOutOfSupabase();
  if (isAuthPath(window.location.pathname)) {
    redirecting = false;
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    return;
  }
  window.location.replace(loginRedirectPath());
}
