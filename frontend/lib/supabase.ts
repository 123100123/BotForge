import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { AUTH_PROVIDER, IS_MOCK, SUPABASE_CONFIG } from "@/lib/config";

/**
 * Supabase, for authentication only (NEXT_PUBLIC_AUTH_PROVIDER=supabase): the app's data always comes
 * from the backend. supabase-js keeps the session (access and refresh token) in localStorage and
 * refreshes the access token before it expires; the backend verifies it on every request.
 */
let client: SupabaseClient | null = null;

const SIGN_OUT_TIMEOUT_MS = 3000;

/** The Supabase client in the browser; null in mock mode, with the own login, and during server rendering. */
export function getSupabase(): SupabaseClient | null {
  if (IS_MOCK || AUTH_PROVIDER !== "supabase" || typeof window === "undefined") return null;
  if (!client) {
    client = createClient(SUPABASE_CONFIG.url, SUPABASE_CONFIG.anonKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  }
  return client;
}

/** The current access token for the backend's Authorization header (refreshed by supabase-js when due); null when signed out. */
export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Drops supabase-js's stored session, also when `signOut` failed or hung (it would otherwise keep the user "signed in"). */
function removeStoredSession(): void {
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith("sb-") && key.includes("-auth-token")) window.localStorage.removeItem(key);
    }
  } catch {
    /* storage unavailable: nothing was stored there either */
  }
}

/**
 * Ends this browser's Supabase session (scope "local": other devices stay signed in, like the own
 * login's logout), and removes the stored session whatever the sign-out request did.
 */
export async function signOutOfSupabase(): Promise<void> {
  const supabase = getSupabase();
  if (!supabase) return;
  try {
    await Promise.race([
      supabase.auth.signOut({ scope: "local" }),
      new Promise((resolve) => setTimeout(resolve, SIGN_OUT_TIMEOUT_MS)),
    ]);
  } catch {
    /* removed below either way */
  }
  removeStoredSession();
}
