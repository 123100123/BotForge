"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Logo } from "@/components/app/logo";
import { ThemeMenu } from "@/components/app/theme-menu";
import { useAuth } from "@/lib/auth";

/** Centered shell for the auth pages; users with a session are sent to the bots list. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace("/bots");
  }, [status, router]);

  return (
    <main className="relative flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-10">
      <div className="absolute end-4 top-4">
        <ThemeMenu />
      </div>
      <Logo size={36} />
      {children}
    </main>
  );
}
