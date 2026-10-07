/**
 * Public runtime configuration. NEXT_PUBLIC_* values are inlined at build time, so each must be
 * referenced literally. Mock mode is on only when NEXT_PUBLIC_MOCK=1. Without it, the Supabase
 * variables are required; when they are missing the app shows a configuration error (see
 * MISSING_CONFIG) instead of quietly falling back to fixtures.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(
  /\/+$/,
  "",
);

export const IS_MOCK: boolean = process.env.NEXT_PUBLIC_MOCK === "1";

/** Names of required variables that are empty in real mode (always empty in mock mode). */
export const MISSING_CONFIG: string[] = IS_MOCK
  ? []
  : [
      ...(SUPABASE_URL.trim() === "" ? ["NEXT_PUBLIC_SUPABASE_URL"] : []),
      ...(SUPABASE_ANON_KEY.trim() === "" ? ["NEXT_PUBLIC_SUPABASE_ANON_KEY"] : []),
    ];

export const SUPABASE_CONFIG = { url: SUPABASE_URL, anonKey: SUPABASE_ANON_KEY };
