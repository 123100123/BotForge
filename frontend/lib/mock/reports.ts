import { capabilitySummaries } from "@/lib/mock/capabilities";
import type { CapabilityReportOut, MetricValue, OverviewOut, Period, SeriesPoint } from "@/lib/types";

/** Demo data for the Overview and per-capability reports. Deterministic per (key, period) so the screens do not flicker. */

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

function ago(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

/** Days covered by each period (the demo charts show one point per day, or per three hours for a single day). */
const PERIOD_DAYS: Record<Period, number> = {
  today: 1,
  yesterday: 1,
  "7d": 7,
  "30d": 30,
  this_week: 7,
  last_week: 7,
  this_month: 30,
  all: 30,
};

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Small deterministic generator (mulberry32). */
function rng(seedText: string): () => number {
  let a = hash(seedText);
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const dayFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { day: "numeric", month: "short", timeZone: "Asia/Tehran" });
const hourFmt = new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Tehran" });

function seriesFor(seed: string, period: Period, base: number): SeriesPoint[] {
  const rand = rng(seed);
  const days = PERIOD_DAYS[period];
  const now = Date.now();
  if (days === 1) {
    return Array.from({ length: 8 }, (_, i) => ({
      label: hourFmt.format(new Date(now - (7 - i) * 3 * HOUR)),
      value: Math.round(base * 0.4 * rand()),
    }));
  }
  return Array.from({ length: days }, (_, i) => ({
    label: dayFmt.format(new Date(now - (days - 1 - i) * DAY)),
    value: Math.round(base * (0.4 + rand())),
  }));
}

function sum(points: SeriesPoint[]): number {
  return points.reduce((total, p) => total + p.value, 0);
}

function scalar(id: string, label: string, value: number, previous: number | null, unit: string | null = null): MetricValue {
  return { id, label, kind: "scalar", value, unit, series: null, rows: null, previous };
}

function series(id: string, label: string, points: SeriesPoint[]): MetricValue {
  return { id, label, kind: "series", value: null, unit: null, series: points, rows: null, previous: null };
}

function breakdown(id: string, label: string, seed: string, groups: string[], base: number): MetricValue {
  const rand = rng(seed);
  const points = groups.map((g) => ({ label: g, value: Math.max(1, Math.round(base * rand())) }));
  return { id, label, kind: "breakdown", value: null, unit: null, series: points, rows: null, previous: null };
}

function table(id: string, label: string, rows: Record<string, unknown>[]): MetricValue {
  return { id, label, kind: "table", value: null, unit: null, series: null, rows, previous: null };
}

function prev(rand: () => number, value: number): number {
  return Math.max(0, Math.round(value * (0.7 + rand() * 0.6)));
}

function metricsFor(key: string, period: Period): MetricValue[] {
  const rand = rng(`${key}:${period}:prev`);
  const base = PERIOD_DAYS[period] === 1 ? 14 : 6;
  const trend = (suffix: string, b = base) => seriesFor(`${key}:${period}:${suffix}`, period, b);
  switch (key) {
    case "booking": {
      const t = trend("t");
      return [
        scalar("bookings_count", "تعداد رزروها", sum(t), prev(rand, sum(t))),
        scalar("occupancy", "درصد اشغال ظرفیت", 40 + Math.round(rand() * 45), 55, "٪"),
        series("bookings_per_day", "رزرو در طول زمان", t),
        breakdown("bookings_by_status", "رزرو بر اساس وضعیت", `${key}:s`, ["تأییدشده", "لیست انتظار", "لغوشده"], 30),
        table("top_services", "پرمراجعه‌ترین خدمات", [
          { خدمت: "کارگاه طراحی لوگو", رزرو: 18, ظرفیت: 20 },
          { خدمت: "مشاورهٔ برند", رزرو: 11, ظرفیت: 15 },
          { خدمت: "دورهٔ فوتوشاپ", رزرو: 7, ظرفیت: 12 },
        ]),
      ];
    }
    case "events":
      return [
        scalar("events_count", "رویدادهای برگزارشده", 4 + Math.round(rand() * 6), 5),
        breakdown("rsvp_breakdown", "اعلام حضور", `${key}:r`, ["می‌آیم", "شاید", "نمی‌آیم"], 40),
        series("events_attendance", "حضور در طول زمان", trend("a", 9)),
      ];
    case "orders": {
      const t = trend("t");
      return [
        scalar("orders_count", "تعداد سفارش‌ها", sum(t), prev(rand, sum(t))),
        scalar("revenue", "درآمد", sum(t) * 540_000, prev(rand, sum(t)) * 540_000, "تومان"),
        series("orders_per_day", "سفارش در طول زمان", t),
        breakdown("orders_by_status", "سفارش بر اساس وضعیت", `${key}:s`, ["جدید", "در حال آماده‌سازی", "ارسال‌شده", "لغوشده"], 20),
      ];
    }
    case "inventory":
      return [
        scalar("low_stock", "محصولات کم‌موجودی", 2 + Math.round(rand() * 3), null),
        table("low_stock_items", "فهرست کمبود", [
          { محصول: "قاب عکس چوبی", موجودی: 2 },
          { محصول: "دفتر یادداشت", موجودی: 1 },
        ]),
      ];
    case "request":
    case "forms":
    case "approvals":
      return [
        scalar("requests_count", "تعداد درخواست‌ها", 9 + Math.round(rand() * 20), 14),
        scalar("pending_approvals", "در انتظار تأیید", Math.round(rand() * 6), null),
        breakdown("requests_by_status", "درخواست بر اساس وضعیت", `${key}:s`, ["جدید", "در حال بررسی", "تأییدشده", "ردشده"], 12),
      ];
    case "feedback":
      return [
        scalar("feedback_average", "میانگین امتیاز (از ۵)", 3.8 + Math.round(rand() * 10) / 10, 4.1),
        series("feedback_trend", "امتیاز در طول زمان", trend("f", 4)),
      ];
    default: {
      const t = trend("t");
      return [scalar("total", "مجموع", sum(t), prev(rand, sum(t))), series("per_day", "روند", t)];
    }
  }
}

function kpis(period: Period): MetricValue[] {
  const rand = rng(`overview:${period}`);
  const k = PERIOD_DAYS[period] === 1 ? 1 : PERIOD_DAYS[period] / 7;
  const pick = (base: number) => Math.round(base * k * (0.8 + rand() * 0.5));
  const customers = pick(24);
  const bookings = pick(37);
  const orders = pick(12);
  return [
    scalar("customers", "مشتریان جدید", customers, prev(rand, customers)),
    scalar("bookings", "رزروها", bookings, prev(rand, bookings)),
    scalar("orders", "سفارش‌ها", orders, prev(rand, orders)),
    scalar("revenue", "درآمد", orders * 700_000, prev(rand, orders) * 700_000, "تومان"),
  ];
}

export function getOverview(period: Period): OverviewOut {
  return {
    period,
    kpis: kpis(period),
    activity: [
      { at: ago(5 * 60_000), text: "علی رضایی در کارگاه «طراحی لوگو» ثبت‌نام کرد.", kind: "booking" },
      { at: ago(32 * 60_000), text: "سفارش جدید به مبلغ ۶۵۰٬۰۰۰ تومان ثبت شد.", kind: "order" },
      { at: ago(2 * HOUR), text: "یک نفر در لیست انتظار قرار گرفت.", kind: "waitlist" },
      { at: ago(5 * HOUR), text: "درخواست پشتیبانی جدید دریافت شد.", kind: "request" },
      { at: ago(DAY), text: "نسخهٔ ۳ ربات فعال شد.", kind: "revision" },
    ],
    enabled_capabilities: capabilitySummaries()
      .filter((c) => c.enabled)
      .map((c) => c.id),
  };
}

export function getCapabilityReport(capKey: string, period: Period): CapabilityReportOut {
  const now = Date.now();
  const found = capabilitySummaries().find((c) => c.id === capKey || c.spec_keys.includes(capKey));
  return {
    capability_key: capKey,
    capability_id: found?.id ?? capKey,
    label: found?.name ?? capKey,
    period,
    since: new Date(now - PERIOD_DAYS[period] * DAY).toISOString(),
    until: new Date(now).toISOString(),
    metrics: metricsFor(capKey, period),
  };
}
