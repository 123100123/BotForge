"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronsUpDown, LayoutGrid, Plus } from "lucide-react";
import { BotStatusChip } from "@/components/app/bot-status-chip";
import { useBusiness } from "@/components/app/business-context";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import { botHref } from "@/lib/routes";
import type { Bot } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Top of the sidebar: the business (name, status word with marker, @handle) and a menu to switch to another
 * business, see them all, or create a new one. The other businesses load when the menu first opens.
 */
export function BusinessSwitcher({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const { bot } = useBusiness();
  const router = useRouter();
  const [others, setOthers] = useState<Bot[] | null>(null);
  const [failed, setFailed] = useState(false);

  function loadOthers() {
    if (others) return;
    api.listBots().then(
      (list) => {
        setOthers(list.filter((b) => b.id !== bot.id));
        setFailed(false);
      },
      () => setFailed(true),
    );
  }

  function go(href: string) {
    onNavigate?.();
    router.push(href);
  }

  return (
    <DropdownMenu onOpenChange={(open) => open && loadOthers()}>
      <DropdownMenuTrigger
        className={cn(
          "flex w-full min-w-0 items-center gap-2 rounded-sm px-2.5 py-2 text-start transition-colors duration-fast hover:bg-surface-sunken data-[state=open]:bg-surface-sunken",
          className,
        )}
        aria-label={`کسب‌وکار: ${bot.name}. تغییر کسب‌وکار`}
      >
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="truncate text-body leading-snug font-semibold text-fg">{bot.name}</span>
          <span className="flex min-w-0 items-center gap-2">
            <BotStatusChip status={bot.status} />
            {bot.tg_username && (
              <span dir="ltr" className="truncate text-caption text-fg-muted">
                @{bot.tg_username}
              </span>
            )}
          </span>
        </span>
        <ChevronsUpDown className="size-4 shrink-0 text-fg-muted" strokeWidth={1.75} aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-[var(--radix-dropdown-menu-trigger-width)] min-w-60">
        <DropdownMenuLabel>کسب‌وکارهای دیگر</DropdownMenuLabel>
        {others === null && !failed && <p className="px-2.5 py-1.5 text-small text-fg-muted">در حال بارگذاری…</p>}
        {failed && <p className="px-2.5 py-1.5 text-small text-fg-muted">فهرست بارگذاری نشد.</p>}
        {others?.length === 0 && <p className="px-2.5 py-1.5 text-small text-fg-muted">کسب‌وکار دیگری ندارید.</p>}
        {others?.map((b) => (
          <DropdownMenuItem key={b.id} onSelect={() => go(botHref(b.id))} className="justify-between gap-3">
            <span className="truncate">{b.name}</span>
            <BotStatusChip status={b.status} />
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => go("/bots?all=1")}>
          <LayoutGrid strokeWidth={1.75} />
          همهٔ کسب‌وکارها
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => go("/bots/new")}>
          <Plus strokeWidth={1.75} />
          کسب‌وکار جدید
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
