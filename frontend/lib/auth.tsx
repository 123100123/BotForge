"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api, UNAUTHORIZED_EVENT } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { Me } from "@/lib/types";

/**
 * Auth against the backend's own cookie sessions. The session is an HttpOnly cookie set by the backend;
 * this module never sees a token. It only asks `GET /me` who is signed in.
 */
export type AppUser = Me;

/** `error`: /me failed for a reason other than "not signed in" (network, 5xx); the session is unknown. */
export type AuthStatus = "loading" | "authenticated" | "anonymous" | "error";

interface AuthContextValue {
  user: AppUser | null;
  status: AuthStatus;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Asks /me again (used by the retry button after status "error"). */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const GENERIC_AUTH_ERROR = "ورود یا ثبت‌نام انجام نشد. دوباره امتحان کنید.";

/** Persian message for a failed login or signup, chosen by the backend's error code. */
export function authErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return GENERIC_AUTH_ERROR;
  switch (err.code) {
    case "email_taken":
      return "با این ایمیل قبلاً ثبت‌نام شده است.";
    case "weak_password":
      return "گذرواژه باید دست‌کم ۱۰ نویسه باشد.";
    case "invalid_email":
      return "ایمیل واردشده معتبر نیست.";
    case "invalid_credentials":
      return "ایمیل یا گذرواژه درست نیست.";
    case "rate_limited":
      return "تعداد تلاش‌ها زیاد بود؛ کمی بعد دوباره امتحان کنید.";
    case "signup_disabled":
      return "ثبت‌نام در حال حاضر غیرفعال است.";
    case "network_error":
      return err.message;
    default:
      return GENERIC_AUTH_ERROR;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
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

  // Any API call that later gets a 401 means the session is gone: drop to signed-out (guard redirects).
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

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** The signed-in user, or null (also while loading; use `useAuth` to distinguish). */
export function useUser(): AppUser | null {
  return useAuth().user;
}

/** Redirects to /login once /me says there is no session. Returns the auth state for the caller to render. */
export function useRequireUser(): AuthContextValue {
  const auth = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (auth.status === "anonymous") router.replace("/login");
  }, [auth.status, router]);
  return auth;
}
