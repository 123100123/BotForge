"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { isNavItemActive, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { SidebarNav } from "./app-sidebar";
import { NAV_ITEM_ACTIVE_CLASS, useNavBadges, type NavBadge } from "./nav-list";

function RailLink({ item, pathname, badge }: { item: NavItem; pathname: string; badge?: NavBadge }) {
  const active = isNavItemActive(item, pathname);
  const Icon = item.icon;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          href={item.href}
          aria-current={active ? "page" : undefined}
          aria-label={badge ? `${item.label} (${badge.label})` : item.label}
          className={cn(
            "relative flex size-11 items-center justify-center rounded-sm text-fg-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-fg",
            active && NAV_ITEM_ACTIVE_CLASS,
          )}
        >
          <Icon className="size-5" strokeWidth={1.75} aria-hidden />
          {badge && <span aria-hidden className="absolute end-1.5 top-1.5 size-2 rounded-full bg-warning" />}
        </Link>
      </TooltipTrigger>
      {/* The rail is on the right (RTL): labels open toward the content. */}
      <TooltipContent side="left">{item.label}</TooltipContent>
    </Tooltip>
  );
}

/** 640–1023px: a 64px icon rail with tooltips; the menu button expands the full sidebar as a sheet. */
export function IconRail() {
  const { nav, bot } = useBusiness();
  const pathname = usePathname();
  const badges = useNavBadges();
  const [expanded, setExpanded] = useState(false);
  const main = nav.filter((g) => g.id !== "settings");
  const settings = nav.find((g) => g.id === "settings");

  return (
    <aside className="sticky top-0 hidden h-dvh w-16 shrink-0 flex-col items-center border-e bg-surface sm:flex lg:hidden">
      <Sheet open={expanded} onOpenChange={setExpanded}>
        <div className="flex h-14 shrink-0 items-center justify-center">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => setExpanded(true)}
                aria-label="باز کردن فهرست کامل"
                className="flex size-11 items-center justify-center rounded-sm text-fg-secondary hover:bg-surface-sunken hover:text-fg"
              >
                <Menu className="size-5" strokeWidth={1.75} aria-hidden />
              </button>
            </TooltipTrigger>
            <TooltipContent side="left">فهرست کامل</TooltipContent>
          </Tooltip>
        </div>
        <SheetContent side="start" className="w-[280px] gap-0 overflow-hidden p-0">
          <SheetTitle className="sr-only">فهرست {bot.name}</SheetTitle>
          <SheetDescription className="sr-only">بخش‌های کسب‌وکار و تغییر کسب‌وکار</SheetDescription>
          <SidebarNav onNavigate={() => setExpanded(false)} inSheet />
        </SheetContent>
      </Sheet>
      <nav aria-label="بخش‌های کسب‌وکار" className="flex min-h-0 w-full flex-1 flex-col items-center">
        <ul className="flex min-h-0 w-full flex-1 flex-col items-center gap-1 overflow-y-auto border-t py-3">
          {main.flatMap((group, gi) => [
            ...(gi > 0 ? [<li key={`sep-${group.id}`} aria-hidden className="my-1 h-px w-8 shrink-0 bg-border" />] : []),
            ...group.items.map((item) => (
              <li key={item.id}>
                <RailLink item={item} pathname={pathname} badge={badges[item.id]} />
              </li>
            )),
          ])}
        </ul>
        {settings && (
          <div className="flex w-full justify-center border-t py-3">
            {settings.items.map((item) => (
              <RailLink key={item.id} item={item} pathname={pathname} badge={badges[item.id]} />
            ))}
          </div>
        )}
      </nav>
    </aside>
  );
}
