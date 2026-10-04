import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { IS_MOCK, SUPABASE_CONFIG } from "@/lib/config";

let client: SupabaseClient | null = null;

/** Supabase is used for authentication only. Returns null in mock mode. */
export function getSupabase(): SupabaseClient | null {
  if (IS_MOCK) return null;
  if (!client) {
    client = createClient(SUPABASE_CONFIG.url, SUPABASE_CONFIG.anonKey);
  }
  return client;
}

/** Current access token for the backend's Authorization header (a placeholder in mock mode). */
export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!supabase) return "mock-token";
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
