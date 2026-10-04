"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";

export interface AppUser {
  id: string;
  email: string;
}

interface AuthContextValue {
  user: AppUser | null;
  /** True until the stored session has been read. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  /** Resolves with `needsConfirmation: true` when the account exists but must confirm its email first. */
  signUp: (email: string, password: string) => Promise<{ needsConfirmation: boolean }>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const MOCK_USER_KEY = "botforge.mock.user";

function readMockUser(): AppUser | null {
  try {
    const raw = window.localStorage.getItem(MOCK_USER_KEY);
    return raw ? (JSON.parse(raw) as AppUser) : null;
  } catch {
    return null;
  }
}

function writeMockUser(user: AppUser | null) {
  try {
    if (user) window.localStorage.setItem(MOCK_USER_KEY, JSON.stringify(user));
    else window.localStorage.removeItem(MOCK_USER_KEY);
  } catch {
    /* storage unavailable: the session just will not survive a reload */
  }
}

/** Persian message for a Supabase auth error. */
export function authErrorMessage(message: string | undefined): string {
  const m = (message ?? "").toLowerCase();
  if (m.includes("invalid login")) return "ایمیل یا گذرواژه درست نیست.";
  if (m.includes("already registered") || m.includes("already been registered"))
    return "با این ایمیل قبلاً ثبت‌نام شده است.";
  if (m.includes("email not confirmed")) return "ایمیل شما هنوز تأیید نشده است.";
  if (m.includes("password") && m.includes("least")) return "گذرواژه باید دست‌کم ۶ نویسه باشد.";
  if (m.includes("rate limit") || m.includes("too many")) return "تعداد تلاش‌ها زیاد بود؛ کمی بعد دوباره امتحان کنید.";
  if (m.includes("fetch") || m.includes("network")) return "اتصال به سرور برقرار نشد.";
  return "ورود یا ثبت‌نام انجام نشد. دوباره امتحان کنید.";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) {
      Promise.resolve(readMockUser()).then((u) => {
        setUser(u);
        setLoading(false);
      });
      return;
    }
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      const u = data.session?.user;
      setUser(u ? { id: u.id, email: u.email ?? "" } : null);
      setLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      const u = session?.user;
      setUser(u ? { id: u.id, email: u.email ?? "" } : null);
      setLoading(false);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const supabase = getSupabase();
    if (!supabase) {
      const u = { id: "mock-user", email };
      writeMockUser(u);
      setUser(u);
      return;
    }
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error(authErrorMessage(error.message));
  }, []);

  const signUp = useCallback(async (email: string, password: string) => {
    const supabase = getSupabase();
    if (!supabase) {
      const u = { id: "mock-user", email };
      writeMockUser(u);
      setUser(u);
      return { needsConfirmation: false };
    }
    const { data, error } = await supabase.auth.signUp({ email, password });
    if (error) throw new Error(authErrorMessage(error.message));
    return { needsConfirmation: !data.session };
  }, []);

  const signOut = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) {
      writeMockUser(null);
      setUser(null);
      return;
    }
    await supabase.auth.signOut();
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut }),
    [user, loading, signIn, signUp, signOut],
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

/** Redirects to /login when there is no session. Returns the user once known, otherwise null. */
export function useRequireUser(): AppUser | null {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);
  return user;
}
