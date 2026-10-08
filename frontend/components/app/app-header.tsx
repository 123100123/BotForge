"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Blocks, LogOut, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/app/theme-toggle";
import { useAuth } from "@/lib/auth";
import { IS_MOCK } from "@/lib/config";

export function AppHeader() {
  const { user, signOut } = useAuth(); const router = useRouter();
  async function onSignOut() { await signOut(); router.replace("/login"); }
  return <header className="sticky top-0 z-30 border-b bg-card/85 backdrop-blur-xl">
    <div className="mx-auto flex min-h-18 w-full max-w-[1600px] flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-6 lg:px-8">
      <Link href="/bots" className="flex shrink-0 items-center gap-2.5 rounded-xl focus-visible:outline-2 focus-visible:outline-primary">
        <span className="grid size-10 place-items-center rounded-xl bg-primary text-white shadow-sm"><Blocks className="size-5" /></span>
        <span><span className="block text-lg font-extrabold tracking-tight">بات‌فورج</span><span className="hidden text-[10px] text-muted-foreground sm:block">سیستم‌عامل کسب‌وکار در تلگرام</span></span>
      </Link>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5 sm:gap-3">
        {IS_MOCK && <span className="hidden items-center gap-1.5 rounded-full border bg-surface-secondary px-2.5 py-1 text-[11px] text-muted-foreground sm:inline-flex"><FlaskConical className="size-3" />نمایشی</span>}
        {user && <span dir="ltr" className="hidden max-w-44 truncate text-xs text-muted-foreground md:inline">{user.email}</span>}
        <ThemeToggle />
        <Button variant="ghost" size="sm" onPress={onSignOut} aria-label="خروج از حساب"><LogOut className="size-4" /><span className="hidden sm:inline">خروج</span></Button>
      </div>
    </div>
  </header>;
}
