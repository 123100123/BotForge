"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRequireUser } from "@/lib/auth";

/**
 * Route guard: everything under /bots needs a session. /me decides: a 401 redirects to /login.
 * The frame is chosen below: (home) pages get the simple header, /bots/[id] the Control Center shell.
 */
export default function BotsLayout({ children }: { children: ReactNode }) {
  const { user, status, refresh } = useRequireUser();

  if (status === "error") {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 px-4 text-center" role="alert">
        <p className="text-small text-fg-muted">ارتباط با سرور برقرار نشد. اینترنت خود را بررسی کنید.</p>
        <Button variant="secondary" size="sm" onClick={() => void refresh()}>
          تلاش دوباره
        </Button>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-fg-muted" role="status">
        <Loader2 className="size-5 animate-spin" aria-label="در حال بارگذاری" />
      </div>
    );
  }

  return <>{children}</>;
}
