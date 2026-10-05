import type {
  CapabilityCategory,
  CapabilityCategoryOut,
  CapabilityConfigIn,
  CapabilityListOut,
  CapabilityOut,
  CapabilityToggleIn,
  CapabilityToggleOut,
  CapabilityTogglePlan,
} from "@/lib/types";
import { ApiError } from "@/lib/errors";

/** Demo data: obviously-sample capabilities across every category, with realistic dependencies. */

const CATEGORY_NAMES: Record<CapabilityCategory, string> = {
  commerce: "فروش",
  operations: "عملیات",
  team: "تیم",
  intelligence: "هوش و گزارش",
  customer: "مشتریان",
};

function cap(
  id: string,
  name: string,
  description: string,
  category: CapabilityCategory,
  rest: Partial<CapabilityOut> = {},
): CapabilityOut {
  return {
    id,
    name,
    description,
    category,
    kind: "spec",
    enabled: false,
    configurable: false,
    requires: [],
    requires_any: [],
    conflicts: [],
    features: [],
    metrics: [],
    audience: null,
    spec_keys: [],
    config: {},
    needs_agent: false,
    handoff_prompt: null,
    ...rest,
  };
}

function seed(): CapabilityOut[] {
  return [
    cap("catalog", "فهرست محصولات", "نمایش محصولات و خدمات در ربات.", "commerce", {
      enabled: true,
      features: ["نمایش جزئیات", "مرتب‌سازی"],
      spec_keys: ["catalog"],
    }),
    cap("orders", "سفارش‌ها", "سبد خرید، ثبت سفارش و پیگیری وضعیت.", "commerce", {
      requires: ["catalog"],
      features: ["سبد خرید", "موجودی", "وضعیت سفارش"],
      metrics: ["orders_count", "revenue"],
      configurable: true,
      config: { low_stock_alert: 3 },
      spec_keys: ["orders"],
    }),
    cap("booking", "رزرو و ثبت‌نام", "رزرو وقت یا ثبت‌نام با ظرفیت و لیست انتظار.", "operations", {
      enabled: true,
      features: ["ظرفیت", "لیست انتظار", "انصراف"],
      metrics: ["bookings_count", "occupancy"],
      configurable: true,
      spec_keys: ["booking"],
    }),
    cap("events", "رویدادها", "رویداد با دسته‌بندی، یادآوری و اعلام حضور.", "operations", {
      requires: ["booking"],
      features: ["دسته‌بندی", "یادآوری", "پست گروه"],
      metrics: ["rsvp_breakdown"],
      configurable: true,
      config: { reminder_hours_before: 24 },
    }),
    cap("requests", "درخواست‌ها و فرم‌ها", "ثبت درخواست مشتری با فرم و گردش تأیید.", "operations", {
      enabled: true,
      features: ["فرم سفارشی", "وضعیت‌ها", "اقدام مدیر"],
      spec_keys: ["request"],
    }),
    cap("staff_roles", "نقش‌ها و تیم", "دعوت کارکنان با لینک و دسترسی مدیر.", "team", {
      kind: "module",
      features: ["لینک دعوت", "نقش کارمند و مدیر"],
    }),
    cap("announcements", "اطلاع‌رسانی", "ارسال پیام همگانی به مشتریان یا گروه‌ها.", "customer", {
      kind: "module",
      requires_any: ["booking", "orders"],
      features: ["مخاطب‌یابی", "گروه تلگرام"],
    }),
    cap("reporting", "گزارش‌ها", "شاخص‌های فروش و فعالیت به‌صورت خودکار.", "intelligence", {
      kind: "module",
      enabled: true,
      features: ["نمای کلی", "گزارش هر قابلیت"],
    }),
    cap("scheduled_reports", "گزارش زمان‌بندی‌شده", "خلاصهٔ روزانه و هفتگی در تلگرام.", "intelligence", {
      kind: "module",
      requires: ["reporting"],
      features: ["خلاصهٔ روزانه", "خلاصهٔ هفتگی"],
    }),
    cap("data_analyst", "تحلیلگر داده", "بارگذاری فایل اکسل و تحلیل خودکار.", "intelligence", {
      kind: "module",
      requires: ["reporting"],
      conflicts: [],
      features: ["پروفایل تحلیل", "هشدار ناهنجاری"],
      needs_agent: true,
      handoff_prompt: "قابلیت تحلیلگر داده را برای ربات فعال کن.",
    }),
  ];
}

let state: CapabilityOut[] | null = null;
function caps(): CapabilityOut[] {
  if (!state) state = seed();
  return state;
}

function find(id: string): CapabilityOut {
  const found = caps().find((c) => c.id === id);
  if (!found) throw new ApiError("not_found", "قابلیت پیدا نشد.", 404);
  return found;
}

export function listCapabilities(): CapabilityListOut {
  const categories: CapabilityCategoryOut[] = (Object.keys(CATEGORY_NAMES) as CapabilityCategory[]).map((id) => ({
    id,
    name: CATEGORY_NAMES[id],
    capabilities: caps()
      .filter((c) => c.category === id)
      .map((c) => ({ ...c })),
  }));
  return { categories };
}

function plan(capId: string, action: "enable" | "disable"): CapabilityTogglePlan {
  const target = find(capId);
  const all = caps();
  const out: CapabilityTogglePlan = {
    capability: capId,
    action,
    will_enable: [],
    will_disable: [],
    blocked_by: [],
    needs_agent: false,
    handoff_prompt: null,
    compat_warnings: [],
  };
  if (action === "enable") {
    for (const dep of target.requires) if (!find(dep).enabled) out.will_enable.push(dep);
    out.blocked_by = target.conflicts.filter((id) => find(id).enabled);
    if (target.requires_any.length > 0 && !target.requires_any.some((id) => find(id).enabled)) {
      out.blocked_by.push(...target.requires_any);
    }
    out.needs_agent = target.needs_agent;
    out.handoff_prompt = target.handoff_prompt;
  } else {
    out.will_disable = all.filter((c) => c.enabled && c.requires.includes(capId)).map((c) => c.id);
  }
  return out;
}

function toggle(capId: string, action: "enable" | "disable", body: CapabilityToggleIn): CapabilityToggleOut {
  const p = plan(capId, action);
  if (body.dry_run || p.blocked_by.length > 0 || p.needs_agent) {
    const message = p.blocked_by.length > 0
      ? "این قابلیت در حال حاضر قابل فعال‌سازی نیست."
      : p.needs_agent
        ? "برای این قابلیت باید از دستیار هوشمند کمک بگیرید."
        : "پیش‌نمایش تغییرات؛ چیزی اعمال نشد.";
    return { plan: p, applied: false, revision_id: null, revision_number: null, message };
  }
  const enabled = action === "enable";
  find(capId).enabled = enabled;
  for (const id of enabled ? p.will_enable : p.will_disable) find(id).enabled = enabled;
  return {
    plan: p,
    applied: true,
    revision_id: "mock-revision",
    revision_number: 99,
    message: enabled ? "قابلیت فعال شد." : "قابلیت غیرفعال شد.",
  };
}

export function enableCapability(capId: string, body: CapabilityToggleIn): CapabilityToggleOut {
  return toggle(capId, "enable", body);
}

export function disableCapability(capId: string, body: CapabilityToggleIn): CapabilityToggleOut {
  return toggle(capId, "disable", body);
}

export function updateCapabilityConfig(capId: string, body: CapabilityConfigIn): CapabilityOut {
  const c = find(capId);
  c.config = { ...c.config, ...body.config };
  return { ...c };
}
