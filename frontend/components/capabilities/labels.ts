import type { CapabilityOut } from "@/lib/types";

/** Capabilities that are listed but cannot be switched on yet. */
export const COMING_SOON = new Set(["payments"]);

/** True while the capability can be switched on (payments is listed as «به‌زودی» and has no switch). */
export function isAvailable(cap: CapabilityOut): boolean {
  return !COMING_SOON.has(cap.id);
}

/** Who sees what a capability adds, as the lead-in of its feature list. */
export const AUDIENCE_SEES: Record<string, string> = {
  everyone: "مشتریان در ربات تلگرام این امکانات را می‌بینند",
  staff: "کارکنان این امکانات را می‌بینند",
  managers: "مدیران این امکانات را می‌بینند",
};

/** Capability id → id of the navigation item (lib/nav.ts) that is its Operations or Insights page. */
export const NAV_ITEM_OF_CAPABILITY: Record<string, string> = {
  orders: "orders",
  booking: "bookings",
  events: "events",
  forms: "requests",
  approvals: "requests",
  announcements: "announcements",
  spreadsheet_intelligence: "spreadsheets",
};

/** Unifies Arabic and Persian letter forms and spacing so a search for «کتاب» also finds «كتاب». */
export function normalizeFa(text: string): string {
  return text
    .replace(/ي/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[‌‎‏]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

export const AUDIENCE_LABELS: Record<string, string> = {
  everyone: "همهٔ کاربران",
  staff: "کارکنان",
  managers: "مدیران",
};

/** Persian names of the metric ids a capability contributes; unknown ids are shown as they are. */
const METRIC_LABELS: Record<string, string> = {
  orders_count: "تعداد سفارش‌ها",
  revenue: "درآمد",
  orders_by_status: "سفارش بر اساس وضعیت",
  bookings_count: "تعداد رزروها",
  bookings_by_status: "رزرو بر اساس وضعیت",
  occupancy: "درصد اشغال ظرفیت",
  rsvp_breakdown: "اعلام حضور رویدادها",
  events_count: "تعداد رویدادها",
  requests_count: "تعداد درخواست‌ها",
  requests_by_status: "درخواست بر اساس وضعیت",
  pending_approvals: "در انتظار تأیید",
  low_stock: "محصولات کم‌موجودی",
  feedback_average: "میانگین امتیاز مشتریان",
};

export function metricLabel(id: string): string {
  return METRIC_LABELS[id] ?? id;
}

/** Persian labels of the simple config fields a module capability can expose. */
const CONFIG_LABELS: Record<string, string> = {
  low_stock_threshold: "آستانهٔ هشدار کم‌موجودی",
  reminder_hours_before: "یادآوری چند ساعت قبل",
};

export function configLabel(key: string): string {
  return CONFIG_LABELS[key] ?? key;
}

/** "A، B و C" style names for a list of capability ids. */
export function namesOf(ids: string[], byId: Map<string, CapabilityOut>): string {
  return ids.map((id) => byId.get(id)?.name ?? id).join("، ");
}
