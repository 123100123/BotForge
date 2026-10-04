"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/** Centered shell for the auth pages; signed-in users are sent to the bots list. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/bots");
  }, [loading, user, router]);

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-10">
      <div className="text-2xl font-bold text-primary">بات‌فورج</div>
      {children}
    </main>
  );
}
