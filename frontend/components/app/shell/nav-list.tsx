"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { ChevronDown, FolderOpen } from "lucide-react";
import { useOptionalAgentRun } from "@/components/agent/agent-run-provider";
import { fa } from "@/lib/format";
import { isNavItemActive, OVERFLOW_LABEL, type NavGroup, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";

/** A count that means work waiting (D04: no decorative badges). `label` is the screen-reader sentence. */
export interface NavBadge {
  count: number;
  label: string;
}

/**
 * Badges per nav item id. Today only «تغییرات» (a proposal waits for the owner); Phase 3 adds Operations
 * counts (new orders, open requests) here, keyed by item id ("orders", "requests", "records:<key>").
 */
export function useNavBadges(): Record<string, NavBadge> {
  const run = useOptionalAgentRun();
  const badges: Record<string, NavBadge> = {};
  if (run?.awaitingOwner) {
    badges.changes = {
      count: 1,
      label: run.status === "waiting_user" ? "یک پیشنهاد منتظر پاسخ شماست" : "یک پیشنهاد منتظر تأیید شماست",
    };
  }
  return badges;
}

export const NAV_ITEM_CLASS =
  "flex min-h-10 items-center gap-3 rounded-sm px-3 py-2 text-small font-medium text-fg-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-fg";
export const NAV_ITEM_ACTIVE_CLASS = "bg-brand-soft font-semibold text-brand-text hover:bg-brand-soft hover:text-brand-text";

export function NavCount({ badge, className }: { badge: NavBadge; className?: string }) {
  return (
    <span className={cn("ms-auto inline-flex h-5 min-w-5 items-center justify-center rounded-xs bg-warning-soft px-1.5 text-caption leading-none font-semibold text-warning-text", className)}>
      <span aria-hidden>{fa(badge.count)}</span>
      <span className="sr-only">{badge.label}</span>
    </span>
  );
}

function NavLink({
  item,
  pathname,
  badge,
  onNavigate,
  large,
}: {
  item: NavItem;
  pathname: string;
  badge?: NavBadge;
  onNavigate?: () => void;
  large?: boolean;
}) {
  const active = isNavItemActive(item, pathname);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={cn(NAV_ITEM_CLASS, large && "min-h-11", active && NAV_ITEM_ACTIVE_CLASS)}
    >
      <Icon className="size-5 shrink-0" strokeWidth={1.75} aria-hidden />
      <span className="min-w-0 truncate">{item.label}</span>
      {badge && <NavCount badge={badge} />}
    </Link>
  );
}

function OverflowItems({
  items,
  pathname,
  onNavigate,
  large,
}: {
  items: NavItem[];
  pathname: string;
  onNavigate?: () => void;
  large?: boolean;
}) {
  const listId = useId();
  const hasActive = items.some((i) => isNavItemActive(i, pathname));
  const [open, setOpen] = useState(hasActive);
  const expanded = open || hasActive;
  return (
    <li>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={() => setOpen((o) => !o)}
        className={cn(NAV_ITEM_CLASS, "w-full text-start", large && "min-h-11")}
      >
        <FolderOpen className="size-5 shrink-0" strokeWidth={1.75} aria-hidden />
        <span className="min-w-0 flex-1 truncate">{OVERFLOW_LABEL}</span>
        <ChevronDown className={cn("size-4 shrink-0 transition-transform duration-fast", expanded && "rotate-180")} strokeWidth={1.75} aria-hidden />
      </button>
      {expanded && (
        <ul id={listId} className="mt-0.5 flex flex-col gap-0.5 ps-4">
          {items.map((item) => (
            <li key={item.id}>
              <NavLink item={item} pathname={pathname} onNavigate={onNavigate} large={large} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** One nav group: a caption (when it has one) and its links. */
export function NavGroupList({
  group,
  pathname,
  badges,
  onNavigate,
  large,
  showLabel = true,
}: {
  group: NavGroup;
  pathname: string;
  badges: Record<string, NavBadge>;
  onNavigate?: () => void;
  /** 44px rows (touch sheets). */
  large?: boolean;
  showLabel?: boolean;
}) {
  const labelId = useId();
  return (
    <div role="group" aria-labelledby={group.label && showLabel ? labelId : undefined} className="flex flex-col gap-1">
      {group.label && showLabel && (
        <p id={labelId} className="px-3 pt-1 text-caption text-fg-muted">
          {group.label}
        </p>
      )}
      <ul className="flex flex-col gap-0.5">
        {group.items.map((item) => (
          <li key={item.id}>
            <NavLink item={item} pathname={pathname} badge={badges[item.id]} onNavigate={onNavigate} large={large} />
          </li>
        ))}
        {group.overflow.length > 0 && <OverflowItems items={group.overflow} pathname={pathname} onNavigate={onNavigate} large={large} />}
      </ul>
    </div>
  );
}
