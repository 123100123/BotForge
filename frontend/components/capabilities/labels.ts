import type { CapabilityOut } from "@/lib/types";

/** Capabilities that are listed but cannot be switched on yet. */
export const COMING_SOON = new Set(["payments"]);

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
