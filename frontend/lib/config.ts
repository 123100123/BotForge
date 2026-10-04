/**
 * Public runtime configuration. NEXT_PUBLIC_* values are inlined at build time, so each must be
 * referenced literally. Mock mode is on when NEXT_PUBLIC_MOCK=1 or when Supabase is not configured.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(
  /\/+$/,
  "",
);

export const IS_MOCK: boolean =
  process.env.NEXT_PUBLIC_MOCK === "1" || SUPABASE_URL === "" || SUPABASE_ANON_KEY === "";

export const SUPABASE_CONFIG = { url: SUPABASE_URL, anonKey: SUPABASE_ANON_KEY };
