import type { CapabilityReportOut, MetricValue, OverviewOut, Period } from "@/lib/types";

/** Demo data for the Overview and per-capability reports. */

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

function ago(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

const WEEK_LABELS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"];

function kpis(): MetricValue[] {
  return [
    { id: "customers", label: "مشتریان جدید", kind: "scalar", value: 24, unit: null, series: null, rows: null, previous: 18 },
    { id: "bookings", label: "رزروها", kind: "scalar", value: 37, unit: null, series: null, rows: null, previous: 41 },
    { id: "orders", label: "سفارش‌ها", kind: "scalar", value: 12, unit: null, series: null, rows: null, previous: 9 },
    { id: "revenue", label: "درآمد", kind: "scalar", value: 8_400_000, unit: "تومان", series: null, rows: null, previous: 6_900_000 },
  ];
}

export function getOverview(period: Period): OverviewOut {
  return {
    period,
    kpis: kpis(),
    activity: [
      { at: ago(5 * 60_000), text: "علی رضایی در کارگاه «طراحی لوگو» ثبت‌نام کرد.", kind: "booking" },
      { at: ago(32 * 60_000), text: "سفارش جدید به مبلغ ۶۵۰٬۰۰۰ تومان ثبت شد.", kind: "order" },
      { at: ago(2 * HOUR), text: "یک نفر در لیست انتظار قرار گرفت.", kind: "waitlist" },
      { at: ago(5 * HOUR), text: "درخواست پشتیبانی جدید دریافت شد.", kind: "request" },
      { at: ago(DAY), text: "نسخهٔ ۳ ربات فعال شد.", kind: "revision" },
    ],
    enabled_capabilities: ["catalog", "booking", "requests", "reporting"],
  };
}

export function getCapabilityReport(capKey: string, period: Period): CapabilityReportOut {
  const now = Date.now();
  return {
    capability_key: capKey,
    capability_id: capKey,
    label: capKey,
    period,
    since: new Date(now - 7 * DAY).toISOString(),
    until: new Date(now).toISOString(),
    metrics: [
      { id: "total", label: "مجموع", kind: "scalar", value: 37, unit: null, series: null, rows: null, previous: 41 },
      {
        id: "per_day",
        label: "روند روزانه",
        kind: "series",
        value: null,
        unit: null,
        series: WEEK_LABELS.map((label, i) => ({ label, value: [3, 5, 4, 8, 6, 7, 4][i] })),
        rows: null,
        previous: null,
      },
      {
        id: "by_status",
        label: "به تفکیک وضعیت",
        kind: "breakdown",
        value: null,
        unit: null,
        series: [
          { label: "تأییدشده", value: 28 },
          { label: "لیست انتظار", value: 6 },
          { label: "لغوشده", value: 3 },
        ],
        rows: null,
        previous: null,
      },
    ],
  };
}
