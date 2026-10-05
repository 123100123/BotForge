"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/** Centered shell for the auth pages; users with a session are sent to the bots list. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace("/bots");
  }, [status, router]);

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-10">
      <div className="text-2xl font-bold text-primary">بات‌فورج</div>
      {children}
    </main>
  );
}
