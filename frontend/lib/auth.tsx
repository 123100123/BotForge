"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { isAuthError, type AuthError, type Session } from "@supabase/supabase-js";
import { api, UNAUTHORIZED_EVENT } from "@/lib/api";
import { AUTH_PROVIDER, IS_MOCK } from "@/lib/config";
import { ApiError } from "@/lib/errors";
import { loginRedirectPath } from "@/lib/session-expiry";
import { getSupabase, signOutOfSupabase } from "@/lib/supabase";
import type { Me } from "@/lib/types";

/**
 * Who is signed in, with the provider of NEXT_PUBLIC_AUTH_PROVIDER (lib/config.ts). The rest of the app
 * only sees `useAuth` / `useRequireUser`, the same for both:
 * - local: the backend's own cookie sessions. The session is an HttpOnly cookie set by the backend; this
 *   module never sees a token. It only asks `GET /me` who is signed in.
 * - supabase: Supabase Auth (supabase-js) signs in, signs up and signs out; its session events decide the
 *   state, and lib/api.ts sends the session's access token to the backend.
 * Mock mode always uses the first one with the mock API.
 */
export type AppUser = Me;

/** `error`: the session could not be read (local: /me failed for a reason other than "not signed in"). */
export type AuthStatus = "loading" | "authenticated" | "anonymous" | "error";

export interface SignUpResult {
  /** Supabase only: the account exists but its email must be confirmed before the first sign-in. */
  needsConfirmation: boolean;
}

interface AuthContextValue {
  user: AppUser | null;
  status: AuthStatus;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<SignUpResult>;
  signOut: () => Promise<void>;
  /** Reads the session again (used by the retry button after status "error"). */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const GENERIC_AUTH_ERROR = "ورود یا ثبت‌نام انجام نشد. دوباره امتحان کنید.";
const NETWORK_ERROR = "ارتباط با سرور برقرار نشد. اینترنت خود را بررسی کنید.";

/** Persian message for a failed login or signup, chosen by the error code (the backend's, or a Supabase one mapped in `supabaseError`). */
export function authErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return GENERIC_AUTH_ERROR;
  switch (err.code) {
    case "email_taken":
      return "با این ایمیل قبلاً ثبت‌نام شده است.";
    case "weak_password":
      return "گذرواژه باید دست‌کم ۱۰ نویسه باشد.";
    case "weak_password_policy":
      return "گذرواژه به اندازهٔ کافی قوی نیست؛ گذرواژهٔ بلندتر و متنوع‌تری انتخاب کنید.";
    case "invalid_email":
      return "ایمیل واردشده معتبر نیست.";
    case "invalid_credentials":
      return "ایمیل یا گذرواژه درست نیست.";
    case "email_not_confirmed":
      return "ایمیل شما هنوز تأیید نشده است. پیوند تأییدی را که برایتان فرستادیم باز کنید.";
    case "rate_limited":
      return "تعداد تلاش‌ها زیاد بود؛ کمی بعد دوباره امتحان کنید.";
    case "signup_disabled":
      return "ثبت‌نام در حال حاضر غیرفعال است.";
    case "network_error":
    case "local_auth_disabled": // the API signs in with Supabase but this build uses the own login
      return err.message;
    default:
      return GENERIC_AUTH_ERROR;
  }
}

/** A Supabase auth error as an ApiError with one of the codes `authErrorMessage` knows. */
function supabaseError(error: AuthError): ApiError {
  const status = error.status ?? 0;
  switch (error.code) {
    case "invalid_credentials":
      return new ApiError("invalid_credentials", GENERIC_AUTH_ERROR, status);
    case "email_not_confirmed":
      return new ApiError("email_not_confirmed", GENERIC_AUTH_ERROR, status);
    case "user_already_exists":
    case "email_exists":
      return new ApiError("email_taken", GENERIC_AUTH_ERROR, status);
    case "weak_password":
      return new ApiError("weak_password_policy", GENERIC_AUTH_ERROR, status);
    case "email_address_invalid":
    case "validation_failed":
      return new ApiError("invalid_email", GENERIC_AUTH_ERROR, status);
    case "over_request_rate_limit":
    case "over_email_send_rate_limit":
      return new ApiError("rate_limited", GENERIC_AUTH_ERROR, status);
    case "signup_disabled":
    case "email_provider_disabled":
      return new ApiError("signup_disabled", GENERIC_AUTH_ERROR, status);
    default:
      // No response at all (offline, blocked): supabase-js reports it without a status.
      return status === 0
        ? new ApiError("network_error", NETWORK_ERROR)
        : new ApiError("auth_failed", GENERIC_AUTH_ERROR, status);
  }
}

/**
 * Runs a supabase-js auth call and returns its result, or throws an ApiError for a failure, whether
 * supabase-js returns it (`error`) or throws it (offline, blocked).
 */
async function supabaseCall<T extends { error: AuthError | null }>(call: () => Promise<T>): Promise<T> {
  let result: T;
  try {
    result = await call();
  } catch (err) {
    throw isAuthError(err) ? supabaseError(err) : new ApiError("network_error", NETWORK_ERROR);
  }
  if (result.error) throw supabaseError(result.error);
  return result;
}

function requireSupabase() {
  const supabase = getSupabase();
  if (!supabase) throw new ApiError("auth_failed", GENERIC_AUTH_ERROR);
  return supabase;
}

function toAppUser(session: Session | null): AppUser | null {
  const user = session?.user;
  return user ? { id: user.id, email: user.email ?? "" } : null;
}

/** The backend's own login (also mock mode): exactly the cookie-session behavior it always had. */
function LocalAuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
      setStatus("authenticated");
    } catch (err) {
      setUser(null);
      setStatus(err instanceof ApiError && err.status === 401 ? "anonymous" : "error");
    }
  }, []);

  useEffect(() => {
    // Initial session load; setState happens after the awaited request, not synchronously in the effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  // The session ended while on an auth page (lib/session-expiry.ts): drop to signed-out.
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setStatus("anonymous");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    setUser(await api.login(email, password));
    setStatus("authenticated");
  }, []);

  const signUp = useCallback(async (email: string, password: string) => {
    setUser(await api.signup(email, password));
    setStatus("authenticated");
    return { needsConfirmation: false };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
      setUser(null);
      setStatus("anonymous");
    } catch {
      await refresh(); // logout failed: find out what the session really is
    }
  }, [refresh]);

  const value = useMemo(
    () => ({ user, status, signIn, signUp, signOut, refresh }),
    [user, status, signIn, signUp, signOut, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Supabase Auth: the session lives in supabase-js; its events (initial session, sign-in, refresh, sign-out) decide the state. */
function SupabaseAuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const apply = useCallback((session: Session | null) => {
    const next = toAppUser(session);
    setUser(next);
    setStatus(next ? "authenticated" : "anonymous");
  }, []);

  const refresh = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data, error } = await supabase.auth.getSession();
    if (error) {
      setUser(null);
      setStatus("error");
      return;
    }
    apply(data.session);
  }, [apply]);

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    // INITIAL_SESSION arrives first (the stored session, or none), then every change. Only state is set
    // here: supabase-js must not be awaited inside this callback.
    const { data } = supabase.auth.onAuthStateChange((_event, session) => apply(session));
    return () => data.subscription.unsubscribe();
  }, [apply]);

  // The session ended while on an auth page (lib/session-expiry.ts): drop to signed-out.
  useEffect(() => {
    const onUnauthorized = () => apply(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [apply]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const supabase = requireSupabase();
      const { data } = await supabaseCall(() => supabase.auth.signInWithPassword({ email, password }));
      apply(data.session);
    },
    [apply],
  );

  const signUp = useCallback(
    async (email: string, password: string): Promise<SignUpResult> => {
      const supabase = requireSupabase();
      const { data } = await supabaseCall(() => supabase.auth.signUp({ email, password }));
      // No session: email confirmation is on (or the address is taken; Supabase answers the same, so
      // nobody learns which addresses have accounts).
      if (!data.session) return { needsConfirmation: true };
      apply(data.session);
      return { needsConfirmation: false };
    },
    [apply],
  );

  const signOut = useCallback(async () => {
    await signOutOfSupabase();
    apply(null);
  }, [apply]);

  const value = useMemo(
    () => ({ user, status, signIn, signUp, signOut, refresh }),
    [user, status, signIn, signUp, signOut, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Both values are fixed at build time, so the choice never changes while the app runs.
  return AUTH_PROVIDER === "supabase" && !IS_MOCK ? (
    <SupabaseAuthProvider>{children}</SupabaseAuthProvider>
  ) : (
    <LocalAuthProvider>{children}</LocalAuthProvider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** The signed-in user, or null (also while loading; use `useAuth` to distinguish). */
export function useUser(): AppUser | null {
  return useAuth().user;
}

/**
 * Redirects to /login once there is no session, with `?next=` back to this page (mock mode keeps its
 * plain /login). Returns the auth state for the caller to render.
 */
export function useRequireUser(): AuthContextValue {
  const auth = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (auth.status === "anonymous") router.replace(IS_MOCK ? "/login" : loginRedirectPath());
  }, [auth.status, router]);
  return auth;
}
