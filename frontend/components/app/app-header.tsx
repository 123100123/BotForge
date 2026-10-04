"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
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
    <header className="border-b bg-card">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-4">
        <Link href="/bots" className="text-base font-bold text-primary">
          بات‌فورج
        </Link>
        <div className="flex items-center gap-3">
          {user && (
            <span dir="ltr" className="hidden max-w-48 truncate text-sm text-muted-foreground sm:inline">
              {user.email}
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={onSignOut}>
            <LogOut className="rtl:-scale-x-100" />
            خروج
          </Button>
        </div>
      </div>
    </header>
  );
}
