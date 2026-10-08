import {
  Blocks,
  CalendarCheck,
  CalendarDays,
  ChartColumn,
  FileSpreadsheet,
  Inbox,
  LayoutDashboard,
  Megaphone,
  PencilLine,
  Settings,
  ShoppingBag,
  Smartphone,
  Table2,
  type LucideIcon,
} from "lucide-react";
import { botHref, sectionHref } from "@/lib/routes";
import type { CapabilityOut, DataCollection } from "@/lib/types";

/**
 * Navigation adapter (D04, D05): the Control Center's grouped navigation, with the Operations items
 * generated from the business's data collections and enabled capabilities. Pure: no React, no fetching.
 */

export type NavGroupId = "overview" | "operations" | "insights" | "build" | "settings";

/** Routes generated for Operations. "records" items carry a `collection`. */
export type OperationsRoute = "orders" | "events" | "bookings" | "requests" | "records" | "announcements";

export interface NavItem {
  /** Stable id: the section name, or `records:<key>` for a resource collection. The shell attaches badges by id. */
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  /** "exact": active only on its own path (Overview). "prefix": also on nested paths (/changes/versions). */
  match: "exact" | "prefix";
  /** Prefix that marks the item active when it differs from `href` (Settings links to its first sub-page). */
  activeBase?: string;
}

export interface NavGroup {
  id: NavGroupId;
  /** Caption above the group; null for groups of one item (Overview, Settings). */
  label: string | null;
  items: NavItem[];
  /** Operations only: resource items beyond the first six entries, shown under «سایر داده‌ها». */
  overflow: NavItem[];
}

/** At most this many Operations rows are shown before resources collapse under «سایر داده‌ها». */
export const MAX_OPERATIONS_ITEMS = 6;
export const OVERFLOW_LABEL = "سایر داده‌ها";

/** The events preset books a resource keyed "event" (registry `_events_ops`; a taken key gets a suffix). */
const EVENT_RESOURCE = /^event(_\d+)?$/;

export function isEventBooking(c: DataCollection): boolean {
  return c.kind === "booking" && typeof c.resource === "string" && EVENT_RESOURCE.test(c.resource);
}

function visible(collections: DataCollection[]): DataCollection[] {
  return collections.filter((c) => c.enabled !== false);
}

/** Resource collections that an events booking books: shown inside «رویدادها», not as their own item. */
function eventResourceKeys(collections: DataCollection[]): Set<string> {
  return new Set(visible(collections).filter(isEventBooking).map((c) => c.resource as string));
}

/**
 * The collection keys an Operations page shows, in display order. Disabled collections are left out of the
 * generated routes (records stay browsable at /records, which lists everything).
 */
export function operationsScope(collections: DataCollection[], route: Exclude<OperationsRoute, "records" | "announcements">): string[] {
  const list = visible(collections);
  switch (route) {
    case "orders":
      return list.filter((c) => c.kind === "orders").map((c) => c.key);
    case "events": {
      const bookings = list.filter(isEventBooking);
      const resources = eventResourceKeys(collections);
      // The events themselves first (create and edit), then the registrations.
      return [...list.filter((c) => c.kind === "resource" && resources.has(c.key)).map((c) => c.key), ...bookings.map((c) => c.key)];
    }
    case "bookings":
      return list.filter((c) => c.kind === "booking" && !isEventBooking(c)).map((c) => c.key);
    case "requests":
      return list.filter((c) => c.kind === "request").map((c) => c.key);
  }
}

function isEnabled(capabilities: CapabilityOut[], id: string): boolean {
  return capabilities.some((c) => c.id === id && c.enabled);
}

/** Operations items, in the order the sidebar shows them. */
export function operationsItems(collections: DataCollection[], capabilities: CapabilityOut[], botId: string): NavItem[] {
  const list = visible(collections);
  const items: NavItem[] = [];
  const add = (id: OperationsRoute, label: string, icon: LucideIcon) =>
    items.push({ id, label, href: sectionHref(botId, id), icon, match: "prefix" });

  if (list.some((c) => c.kind === "orders")) add("orders", "سفارش‌ها", ShoppingBag);
  if (list.some(isEventBooking)) add("events", "رویدادها", CalendarDays);
  if (list.some((c) => c.kind === "booking" && !isEventBooking(c))) add("bookings", "رزروها", CalendarCheck);
  if (list.some((c) => c.kind === "request")) add("requests", "درخواست‌ها", Inbox);

  const folded = eventResourceKeys(collections);
  for (const c of list) {
    if (c.kind !== "resource" || folded.has(c.key)) continue;
    items.push({
      id: `records:${c.key}`,
      label: c.label_plural,
      href: sectionHref(botId, "records", { collection: c.key }),
      icon: Table2,
      match: "exact",
    });
  }

  if (isEnabled(capabilities, "announcements")) add("announcements", "اطلاع‌رسانی", Megaphone);
  return items;
}

/** Splits Operations items so that at most MAX_OPERATIONS_ITEMS rows show; only resource items overflow. */
function splitOperations(items: NavItem[]): { items: NavItem[]; overflow: NavItem[] } {
  if (items.length <= MAX_OPERATIONS_ITEMS) return { items, overflow: [] };
  const fixed = items.filter((i) => !i.id.startsWith("records:"));
  const resources = items.filter((i) => i.id.startsWith("records:"));
  // The «سایر داده‌ها» toggle takes one row.
  const room = Math.max(0, MAX_OPERATIONS_ITEMS - fixed.length - 1);
  const shown = new Set(resources.slice(0, room).map((i) => i.id));
  return {
    items: items.filter((i) => !i.id.startsWith("records:") || shown.has(i.id)),
    overflow: resources.filter((i) => !shown.has(i.id)),
  };
}

/** The whole Control Center navigation for one business. */
export function buildNav(collections: DataCollection[], capabilities: CapabilityOut[], botId: string): NavGroup[] {
  const ops = splitOperations(operationsItems(collections, capabilities, botId));
  const insights: NavItem[] = [{ id: "reports", label: "گزارش‌ها", href: sectionHref(botId, "reports"), icon: ChartColumn, match: "prefix" }];
  if (isEnabled(capabilities, "spreadsheet_intelligence")) {
    insights.push({ id: "spreadsheets", label: "تحلیل فایل اکسل", href: sectionHref(botId, "spreadsheets"), icon: FileSpreadsheet, match: "prefix" });
  }

  const groups: NavGroup[] = [
    {
      id: "overview",
      label: null,
      items: [{ id: "overview", label: "نمای کلی", href: sectionHref(botId, "overview"), icon: LayoutDashboard, match: "exact" }],
      overflow: [],
    },
    { id: "operations", label: "عملیات", items: ops.items, overflow: ops.overflow },
    { id: "insights", label: "تحلیل", items: insights, overflow: [] },
    {
      id: "build",
      label: "ساخت",
      items: [
        { id: "capabilities", label: "قابلیت‌ها", href: sectionHref(botId, "capabilities"), icon: Blocks, match: "prefix" },
        { id: "changes", label: "تغییرات", href: sectionHref(botId, "changes"), icon: PencilLine, match: "prefix" },
        { id: "test", label: "آزمایش ربات", href: sectionHref(botId, "test"), icon: Smartphone, match: "prefix" },
      ],
      overflow: [],
    },
    {
      id: "settings",
      label: null,
      items: [
        {
          id: "settings",
          label: "تنظیمات",
          href: sectionHref(botId, "settings"),
          activeBase: `${botHref(botId)}/settings`,
          icon: Settings,
          match: "prefix",
        },
      ],
      overflow: [],
    },
  ];
  return groups.filter((g) => g.items.length > 0 || g.overflow.length > 0);
}

/** True when `item` is the page at `pathname` (or, for prefix items, one of its sub-pages). */
export function isNavItemActive(item: NavItem, pathname: string): boolean {
  const path = pathname.replace(/\/+$/, "");
  const href = (item.activeBase ?? item.href).replace(/\/+$/, "");
  if (item.match === "exact") return path === href;
  return path === href || path.startsWith(`${href}/`);
}

/** The first Operations route of a business (where the legacy "data" links go), or null when there is none. */
export function firstOperationsHref(groups: NavGroup[]): string | null {
  const ops = groups.find((g) => g.id === "operations");
  return ops?.items[0]?.href ?? ops?.overflow[0]?.href ?? null;
}
