"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { AppHeader } from "@/components/app/app-header";
import { useRequireUser } from "@/lib/auth";

/** Route guard: everything under /bots needs a session; otherwise redirect to /login. */
export default function BotsLayout({ children }: { children: ReactNode }) {
  const user = useRequireUser();

  if (!user) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-muted-foreground" role="status">
        <Loader2 className="size-5 animate-spin" aria-label="در حال بارگذاری" />
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
