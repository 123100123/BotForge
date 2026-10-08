"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AppHeader } from "@/components/app/app-header";
import { useRequireUser } from "@/lib/auth";

/** Route guard: everything under /bots needs a session. /me decides: a 401 redirects to /login. */
export default function BotsLayout({ children }: { children: ReactNode }) {
  const { user, status, refresh } = useRequireUser();

  if (status === "error") {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 px-4 text-center" role="alert">
        <p className="text-sm text-muted-foreground">ارتباط با سرور برقرار نشد. اینترنت خود را بررسی کنید.</p>
        <Button variant="outline" size="sm" onPress={() => void refresh()}>
          تلاش دوباره
        </Button>
      </div>
    );
  }

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
      <main className="mx-auto w-full max-w-[1600px] min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
    </div>
  );
}
