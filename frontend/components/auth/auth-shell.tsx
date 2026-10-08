"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Logo } from "@/components/app/logo";
import { ThemeMenu } from "@/components/app/theme-menu";
import { useAuth } from "@/lib/auth";
import { postLoginPath } from "@/lib/session-expiry";

interface AuthShellValue {
  /** The email typed so far. It lives here (the layout is shared by /login and /signup), so switching keeps it. */
  email: string;
  setEmail: (email: string) => void;
  /**
   * Where to go once the session exists (default: the validated `?next=`, otherwise «/bots»). Set before
   * submitting, read by the redirect below.
   */
  setAfterAuth: (path: string | null) => void;
}

const AuthShellContext = createContext<AuthShellValue | null>(null);

export function useAuthShell(): AuthShellValue {
  const ctx = useContext(AuthShellContext);
  if (!ctx) throw new Error("useAuthShell must be used inside AuthShell");
  return ctx;
}

/**
 * Shared frame of /login and /signup. Below 1024px: the mark on top and the form only. From 1024px: the form
 * panel at the start edge and a brand-soft panel (`aside`) at the end edge. Users who already have a session
 * are sent on: to the page chosen by the form that just signed them in, otherwise to the validated `?next=`
 * (lib/session-expiry.ts; set when a 401 sent them here), otherwise to the bots list.
 */
export function AuthShell({ children, aside }: { children: ReactNode; aside: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const afterAuth = useRef<string | null>(null);

  useEffect(() => {
    if (status === "authenticated") router.replace(afterAuth.current ?? postLoginPath());
  }, [status, router]);

  const value = useMemo<AuthShellValue>(
    () => ({
      email,
      setEmail,
      setAfterAuth: (path) => {
        afterAuth.current = path;
      },
    }),
    [email],
  );

  return (
    <AuthShellContext.Provider value={value}>
      <div className="grid min-h-dvh lg:grid-cols-2">
        <div className="flex min-w-0 flex-col px-4 py-4 sm:px-8 lg:px-14">
          <header className="flex items-center justify-between">
            <Link href="/" className="rounded-xs" aria-label="بات‌فورج، صفحهٔ اصلی">
              <Logo size={30} />
            </Link>
            <ThemeMenu />
          </header>
          <main className="flex flex-1 items-start justify-center py-10 lg:pt-[12vh]">
            <div className="w-full max-w-[420px]">{children}</div>
          </main>
        </div>
        <aside className="hidden items-center justify-center border-s border-border bg-brand-soft px-14 py-16 lg:flex">{aside}</aside>
      </div>
    </AuthShellContext.Provider>
  );
}
