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

/** Demo data: obviously-sample capabilities across every category, using the registry ids. */

const CATEGORY_NAMES: Record<CapabilityCategory, string> = {
  commerce: "تجارت",
  operations: "عملیات",
  team: "تیم",
  intelligence: "هوش کسب‌وکار",
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
    // تجارت
    cap("catalog", "فهرست محصولات", "نمایش محصولات و خدمات همراه با قیمت و جزئیات در ربات.", "commerce", {
      enabled: true,
      audience: "everyone",
      features: ["نمایش جزئیات", "مرتب‌سازی", "دسته‌بندی"],
      spec_keys: ["catalog"],
    }),
    cap("orders", "سفارش‌ها", "سبد خرید، ثبت سفارش و پیگیری وضعیت سفارش توسط مشتری و مدیر.", "commerce", {
      requires: ["catalog"],
      audience: "everyone",
      features: ["سبد خرید", "ثبت سفارش", "وضعیت سفارش"],
      metrics: ["orders_count", "revenue", "orders_by_status"],
      configurable: true,
      spec_keys: ["orders"],
      needs_agent: true,
      handoff_prompt: "قابلیت سفارش را برای ربات فعال کن و از من بپرس قیمت محصولات چگونه ثبت شود.",
    }),
    cap("inventory", "موجودی انبار", "پیگیری موجودی هر محصول و هشدار کمبود.", "commerce", {
      kind: "module",
      requires: ["catalog"],
      features: ["موجودی هر محصول", "هشدار کمبود"],
      metrics: ["low_stock"],
      configurable: true,
      config: { low_stock_threshold: 3 },
    }),
    cap("payments", "پرداخت آنلاین", "دریافت پرداخت از مشتری داخل تلگرام.", "commerce", {
      requires: ["orders"],
      features: ["درگاه پرداخت"],
    }),
    // عملیات
    cap("booking", "رزرو و ثبت‌نام", "رزرو وقت یا ثبت‌نام با ظرفیت، لیست انتظار و انصراف.", "operations", {
      enabled: true,
      audience: "everyone",
      features: ["ظرفیت", "لیست انتظار", "انصراف"],
      metrics: ["bookings_count", "bookings_by_status", "occupancy"],
      configurable: true,
      spec_keys: ["booking"],
    }),
    cap("events", "رویدادها", "رویداد با دسته‌بندی، یادآوری خودکار و اعلام حضور.", "operations", {
      requires: ["booking"],
      audience: "everyone",
      features: ["دسته‌بندی", "یادآوری", "اعلام حضور"],
      metrics: ["rsvp_breakdown", "events_count"],
      configurable: true,
      config: { reminder_hours_before: 24 },
    }),
    cap("forms", "فرم‌ها و درخواست‌ها", "ثبت درخواست مشتری با فرم سفارشی و پیگیری وضعیت.", "operations", {
      enabled: true,
      audience: "everyone",
      features: ["فرم سفارشی", "وضعیت‌ها", "اقدام مدیر"],
      metrics: ["requests_count", "requests_by_status"],
      spec_keys: ["request"],
    }),
    cap("approvals", "تأیید و مجوز", "گردش تأیید مدیر برای درخواست‌هایی مثل مرخصی یا خرید.", "operations", {
      requires: ["forms"],
      audience: "managers",
      features: ["صف تأیید", "تأیید یا رد با دلیل"],
      metrics: ["pending_approvals"],
      configurable: true,
    }),
    // تیم
    cap("staff", "کارکنان و نقش‌ها", "دعوت کارکنان با لینک و تعیین نقش کارمند یا مدیر.", "team", {
      kind: "module",
      features: ["لینک دعوت", "نقش کارمند و مدیر"],
    }),
    cap("staff_reporting", "گزارش کارکنان", "کارکنان وضعیت کار را مستقیم از تلگرام گزارش می‌دهند.", "team", {
      kind: "module",
      requires: ["staff", "reporting"],
      features: ["گزارش از تلگرام", "خلاصهٔ مدیر"],
    }),
    // هوش کسب‌وکار
    cap("reporting", "گزارش‌ها", "شاخص‌های فروش و فعالیت به‌صورت خودکار.", "intelligence", {
      kind: "module",
      enabled: true,
      features: ["نمای کلی", "گزارش هر قابلیت"],
    }),
    cap("spreadsheet_intelligence", "هوش صفحه‌گسترده", "بارگذاری فایل اکسل، پروفایل ستون‌ها و تحلیل خودکار.", "intelligence", {
      kind: "module",
      requires: ["reporting"],
      features: ["پروفایل تحلیل", "هشدار تغییر ساختار فایل"],
    }),
    cap("scheduled_reports", "گزارش زمان‌بندی‌شده", "خلاصهٔ روزانه و هفتگی در تلگرام.", "intelligence", {
      kind: "module",
      requires: ["reporting"],
      features: ["خلاصهٔ روزانه", "خلاصهٔ هفتگی"],
    }),
    cap("copilot", "دستیار هوشمند", "از کسب‌وکارتان بپرسید و تغییرات را با دستیار انجام دهید.", "intelligence", {
      kind: "module",
      enabled: true,
      features: ["پرسش از داده‌ها", "تغییر ربات"],
    }),
    // مشتریان
    cap("info", "اطلاعات کسب‌وکار", "ساعت کاری، آدرس، تماس و سؤالات متداول.", "customer", {
      enabled: true,
      audience: "everyone",
      features: ["ساعت کاری", "آدرس", "سؤالات متداول"],
      spec_keys: ["info"],
    }),
    cap("support", "پشتیبانی", "دریافت پیام مشتری و ارجاع آن به تیم.", "customer", {
      requires: ["forms"],
      audience: "everyone",
      features: ["ثبت درخواست پشتیبانی", "پیگیری"],
    }),
    cap("feedback", "بازخورد مشتریان", "جمع‌آوری امتیاز و نظر مشتریان.", "customer", {
      requires: ["forms"],
      audience: "everyone",
      features: ["امتیاز", "نظر"],
      metrics: ["feedback_average"],
    }),
    cap("announcements", "اطلاع‌رسانی", "ارسال پیام همگانی به مشتریان یا گروه‌ها.", "customer", {
      kind: "module",
      requires_any: ["booking", "orders"],
      features: ["مخاطب‌یابی", "گروه تلگرام"],
    }),
  ];
}

let state: CapabilityOut[] | null = null;
let revisionCounter = 4;
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
    if (capId === "events") out.compat_warnings.push("یادآوری رویدادها فقط برای کسانی ارسال می‌شود که ربات را شروع کرده‌اند.");
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
    revision_number: ++revisionCounter,
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
  const { audience, ...rest } = body.config;
  if (typeof audience === "string") c.audience = audience;
  c.config = { ...c.config, ...rest };
  return { ...c };
}

/** Names and enabled state, for the other mocks (Overview and Reports stay consistent with the Capability Center). */
export function capabilitySummaries(): { id: string; name: string; enabled: boolean; spec_keys: string[]; metrics: string[] }[] {
  return caps().map(({ id, name, enabled, spec_keys, metrics }) => ({ id, name, enabled, spec_keys, metrics }));
}
