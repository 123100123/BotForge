"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { useOptionalAgentRun } from "@/components/agent/agent-run-provider";
import type { AttentionTone } from "@/components/app/attention-list";
import { useBusiness } from "@/components/app/business-context";
import { api } from "@/lib/api";
import { fa } from "@/lib/format";
import { operationsScope } from "@/lib/nav";
import { sectionHref } from "@/lib/routes";
import { isPollingConflict } from "@/lib/telegram";
import type { Bot, CapabilityOut, DataCollection, DataRecord } from "@/lib/types";

/**
 * Needs-attention adapter (D07): assembles the Overview's attention list, the upcoming list and the nav counts
 * from endpoints that already exist. Each source is read on its own (settled), so one failing source never
 * hides the others. Results are cached per business and shared by every caller (Overview, sidebar badges).
 */

export type { AttentionTone };

export interface AttentionItem {
  id: string;
  tone: AttentionTone;
  /** A full sentence; it already contains the count. */
  text: string;
  count?: number;
  href: string;
  actionLabel: string;
}

export interface UpcomingItem {
  id: string;
  title: string;
  /** ISO start time. */
  at: string;
  href: string;
}

/** Records waiting in their collection's first status. `more` = the count is a lower bound (page of 50). */
export interface PendingCount {
  count: number;
  more: boolean;
  /** The status the records wait in; the Operations pages filter on it with `?status=`. */
  status: string;
}

interface Sources {
  orders: PendingCount | null;
  requests: PendingCount | null;
  /** null = not applicable (capability off) */
  schemaChanged: number | null;
  events: { soon: number; upcoming: UpcomingItem[] } | null;
  /** The poller parked the bot because another server polls the same Telegram bot (POLLING_CONFLICT). */
  telegramConflict: boolean;
  /** How many of the attempted sources failed. */
  failed: number;
}

const PAGE = 50;
const HOUR = 3_600_000;
const FRESH_MS = 30_000;

function countLabel(p: PendingCount): string {
  return p.more || p.count >= PAGE ? `${fa(PAGE)}+` : fa(p.count);
}

async function pendingCount(botId: string, cols: DataCollection[]): Promise<PendingCount | null> {
  const usable = cols.filter((c) => c.statuses && c.statuses.length > 0);
  if (usable.length === 0) return null;
  const results = await Promise.allSettled(
    usable.map(async (c) => {
      const status = c.statuses![0].key;
      const page = await api.listRecords(botId, c.key, { limit: PAGE });
      return { status, count: page.items.filter((r) => r.status === status).length, more: page.total > page.items.length };
    }),
  );
  const ok = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
  if (ok.length === 0) throw new Error("pending");
  return { status: ok[0].status, count: ok.reduce((n, r) => n + r.count, 0), more: ok.some((r) => r.more) };
}

function startFieldOf(col: DataCollection): string | null {
  const dt = col.fields.filter((f) => f.type === "datetime");
  return (dt.find((f) => f.key === "starts_at") ?? dt[0])?.key ?? null;
}

function titleOf(col: DataCollection, r: DataRecord): string {
  const v = col.title_field ? r.data[col.title_field] : null;
  if (typeof v === "string" && v.trim()) return v;
  return col.label;
}

/**
 * The resource collections whose records have a start time worth listing under «پیش رو»: the events
 * themselves, and the resources that any other booking collection books (workshops, appointments).
 */
export function upcomingResources(collections: DataCollection[]): DataCollection[] {
  const visible = collections.filter((c) => c.enabled !== false);
  const booked = new Set(visible.filter((c) => c.kind === "booking" && c.resource).map((c) => c.resource as string));
  for (const key of operationsScope(collections, "events")) booked.add(key);
  return visible.filter((c) => c.kind === "resource" && booked.has(c.key) && startFieldOf(c) !== null);
}

async function upcomingEvents(botId: string, collections: DataCollection[]): Promise<{ soon: number; upcoming: UpcomingItem[] } | null> {
  const resources = upcomingResources(collections);
  if (resources.length === 0) return null;
  const eventKeys = new Set(operationsScope(collections, "events"));
  const now = Date.now();
  const results = await Promise.allSettled(
    resources.map(async (col) => {
      const field = startFieldOf(col)!;
      const href = sectionHref(botId, eventKeys.has(col.key) ? "events" : "bookings");
      const page = await api.listRecords(botId, col.key, { limit: PAGE });
      return page.items.flatMap((r) => {
        const raw = r.data[field];
        const t = typeof raw === "string" ? new Date(raw).getTime() : NaN;
        if (Number.isNaN(t) || t < now || t > now + 7 * 24 * HOUR) return [];
        return [{ id: `${col.key}:${r.id}`, title: titleOf(col, r), at: new Date(t).toISOString(), href, isEvent: eventKeys.has(col.key) }];
      });
    }),
  );
  if (results.every((r) => r.status === "rejected")) throw new Error("events");
  const ok = results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
  ok.sort((a, b) => a.at.localeCompare(b.at));
  const soon = ok.filter((u) => u.isEvent && new Date(u.at).getTime() <= now + 48 * HOUR).length;
  return { soon, upcoming: ok.map((u) => ({ id: u.id, title: u.title, at: u.at, href: u.href })) };
}

async function schemaChangedCount(botId: string): Promise<number> {
  const runs = await api.listAnalysisRuns(botId);
  const since = Date.now() - 7 * 24 * HOUR;
  return runs.filter((r) => r.status === "schema_changed" && new Date(r.created_at).getTime() >= since).length;
}

async function telegramConflict(botId: string): Promise<boolean> {
  return isPollingConflict((await api.getTelegram(botId)).last_error);
}

async function loadSources(
  botId: string,
  collections: DataCollection[],
  spreadsheets: boolean,
  telegramConnected: boolean,
): Promise<Sources> {
  const visible = collections.filter((c) => c.enabled !== false);
  const ordersCols = visible.filter((c) => c.kind === "orders");
  const requestCols = visible.filter((c) => c.kind === "request");
  const [orders, requests, schema, events, conflict] = await Promise.allSettled([
    ordersCols.length ? pendingCount(botId, ordersCols) : Promise.resolve(null),
    requestCols.length ? pendingCount(botId, requestCols) : Promise.resolve(null),
    spreadsheets ? schemaChangedCount(botId) : Promise.resolve(null),
    upcomingEvents(botId, collections),
    telegramConnected ? telegramConflict(botId) : Promise.resolve(false),
  ]);
  const value = <T,>(r: PromiseSettledResult<T | null>): T | null => (r.status === "fulfilled" ? r.value : null);
  return {
    orders: value(orders),
    requests: value(requests),
    schemaChanged: value(schema),
    events: value(events),
    telegramConflict: value(conflict) === true,
    failed: [orders, requests, schema, events, conflict].filter((r) => r.status === "rejected").length,
  };
}

/* ---------------------------------------------------------------- cache shared by every caller */

interface CacheEntry {
  at: number;
  promise: Promise<Sources>;
}
const cache = new Map<string, CacheEntry>();

function sourcesFor(
  key: string,
  botId: string,
  collections: DataCollection[],
  spreadsheets: boolean,
  telegramConnected: boolean,
  force = false,
): Promise<Sources> {
  const hit = cache.get(key);
  if (hit && !force && Date.now() - hit.at < FRESH_MS) return hit.promise;
  const promise = loadSources(botId, collections, spreadsheets, telegramConnected);
  cache.set(key, { at: Date.now(), promise });
  return promise;
}

/** Forget the cached counts of a business (call after the owner changed records, so the next read is fresh). */
export function invalidateAttention(botId: string): void {
  for (const k of [...cache.keys()]) if (k.startsWith(`${botId}|`)) cache.delete(k);
}

/* ---------------------------------------------------------------- setup gaps */

export interface SetupGaps {
  noVersion: boolean;
  noTelegram: boolean;
  ownerNotLinked: boolean;
  /** True when the setup checklist should show. */
  any: boolean;
}

export function setupGaps(bot: Bot): SetupGaps {
  const noVersion = bot.active_revision_id === null;
  const noTelegram = bot.tg_username === null;
  const ownerNotLinked = !bot.owner_linked;
  return { noVersion, noTelegram, ownerNotLinked, any: noVersion || noTelegram || ownerNotLinked };
}

function buildItems(
  bot: Bot,
  s: Sources | null,
  awaitingOwner: { waiting: boolean; asking: boolean },
  gaps: SetupGaps,
): AttentionItem[] {
  const id = bot.id;
  const items: AttentionItem[] = [];
  if (s?.telegramConflict) {
    items.push({
      id: "telegram-conflict",
      tone: "danger",
      text: "دریافت پیام‌های تلگرام متوقف شده است",
      href: sectionHref(id, "telegram"),
      actionLabel: "بررسی و تلاش دوباره",
    });
  }
  if (awaitingOwner.waiting) {
    items.push({
      id: "changes",
      tone: "brand",
      text: awaitingOwner.asking ? "دستیار برای ادامهٔ تغییر از شما پاسخ می‌خواهد." : "یک پیشنهاد تغییر منتظر تأیید شماست.",
      count: 1,
      href: sectionHref(id, "changes"),
      actionLabel: "بررسی",
    });
  }
  if (s?.orders && s.orders.count > 0) {
    items.push({
      id: "orders",
      tone: "warning",
      text: `${countLabel(s.orders)} سفارش جدید منتظر تأیید`,
      count: s.orders.count,
      href: `${sectionHref(id, "orders")}?status=${encodeURIComponent(s.orders.status)}`,
      actionLabel: "مشاهدهٔ سفارش‌ها",
    });
  }
  if (s?.requests && s.requests.count > 0) {
    items.push({
      id: "requests",
      tone: "warning",
      text: `${countLabel(s.requests)} درخواست باز`,
      count: s.requests.count,
      href: `${sectionHref(id, "requests")}?status=${encodeURIComponent(s.requests.status)}`,
      actionLabel: "مشاهدهٔ درخواست‌ها",
    });
  }
  if (s?.schemaChanged) {
    items.push({
      id: "spreadsheets",
      tone: "warning",
      text: `ساختار ستون‌ها در ${fa(s.schemaChanged)} فایل اکسل اخیر عوض شده است`,
      count: s.schemaChanged,
      href: sectionHref(id, "spreadsheets"),
      actionLabel: "بررسی فایل‌ها",
    });
  }
  if (s?.events && s.events.soon > 0) {
    items.push({
      id: "events",
      tone: "info",
      text: `${fa(s.events.soon)} رویداد تا ۴۸ ساعت دیگر شروع می‌شود`,
      count: s.events.soon,
      href: sectionHref(id, "events"),
      actionLabel: "مشاهدهٔ رویدادها",
    });
  }
  if (gaps.noVersion) {
    items.push({ id: "setup-version", tone: "brand", text: "هنوز نسخه‌ای فعال نیست؛ کسب‌وکارتان را توضیح دهید.", href: sectionHref(id, "changes"), actionLabel: "شروع" });
  }
  if (gaps.noTelegram) {
    items.push({ id: "setup-telegram", tone: "warning", text: "ربات هنوز به تلگرام وصل نیست.", href: sectionHref(id, "telegram"), actionLabel: "اتصال به تلگرام" });
  } else if (gaps.ownerNotLinked) {
    items.push({ id: "setup-owner", tone: "warning", text: "حساب مدیر به ربات وصل نیست.", href: sectionHref(id, "telegram"), actionLabel: "اتصال حساب مدیر" });
  }
  return items;
}

export interface AttentionState {
  items: AttentionItem[];
  /** Events and bookings starting in the next 7 days, soonest first. */
  upcoming: UpcomingItem[];
  orders: PendingCount | null;
  requests: PendingCount | null;
  gaps: SetupGaps;
  /** True until the first read finished; synchronous items (changes, setup) are already in `items`. */
  loading: boolean;
  /** Number of sources that failed to load. */
  failed: number;
  refresh: () => void;
}

/**
 * Needs-attention items, upcoming events and pending counts for the current business. Safe to call from
 * several components: the reads are shared and cached for 30 seconds, and refreshed when the route changes.
 */
export function useAttention(): AttentionState {
  const { bot, collections, capabilities, dataStatus } = useBusiness();
  const run = useOptionalAgentRun();
  const pathname = usePathname();
  const spreadsheets = isEnabled(capabilities, "spreadsheet_intelligence");
  const telegramConnected = bot.tg_username !== null;
  const key = `${bot.id}|${bot.active_revision_id ?? ""}|${collections.map((c) => `${c.key}:${c.enabled !== false}`).join(",")}|${spreadsheets}|${telegramConnected}`;
  const [snap, setSnap] = useState<{ key: string; sources: Sources } | null>(null);
  const [tick, setTick] = useState(0);
  const ready = dataStatus === "ready";

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    void sourcesFor(key, bot.id, collections, spreadsheets, telegramConnected, tick > 0).then((sources) => {
      if (!cancelled) setSnap({ key, sources });
    });
    return () => {
      cancelled = true;
    };
    // `collections` is identified by `key`; `pathname` re-checks freshness when the owner moves around.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready, tick, pathname]);

  const refresh = useCallback(() => {
    invalidateAttention(bot.id);
    setTick((t) => t + 1);
  }, [bot.id]);

  const sources = snap && snap.key === key ? snap.sources : null;
  const gaps = useMemo(() => setupGaps(bot), [bot]);
  const waiting = run?.awaitingOwner ?? false;
  const asking = run?.status === "waiting_user";
  const items = useMemo(() => buildItems(bot, sources, { waiting, asking }, gaps), [bot, sources, waiting, asking, gaps]);

  return {
    items,
    upcoming: sources?.events?.upcoming ?? [],
    orders: sources?.orders ?? null,
    requests: sources?.requests ?? null,
    gaps,
    loading: !sources,
    failed: sources?.failed ?? 0,
    refresh,
  };
}

function isEnabled(capabilities: CapabilityOut[], id: string): boolean {
  return capabilities.some((c) => c.id === id && c.enabled);
}
