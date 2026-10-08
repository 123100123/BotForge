"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Logo } from "@/components/app/logo";
import { ThemeMenu } from "@/components/app/theme-menu";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

export function AppHeader() {
  const { user, signOut } = useAuth();
  const router = useRouter();

  async function onSignOut() {
    await signOut();
    router.replace("/login");
  }

  return (
    <header className="border-b bg-surface">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-4">
        <Link href="/bots" aria-label="بات‌فورج" className="rounded-xs">
          <Logo size={26} />
        </Link>
        <div className="flex items-center gap-2">
          {user && (
            <span dir="ltr" className="hidden max-w-48 truncate text-sm text-muted-foreground sm:inline">
              {user.email}
            </span>
          )}
          <ThemeMenu />
          <Button variant="ghost" size="sm" onClick={onSignOut}>
            <LogOut className="rtl:-scale-x-100" />
            خروج
          </Button>
        </div>
      </div>
    </header>
  );
}
