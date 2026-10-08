import type { CapabilityType, ErrorCode, Phase, RequirementKind, RiskLevel, RunKind, RunStatus } from "@/lib/types";

export const PHASE_LABELS: Record<Phase, string> = {
  triage: "بررسی پیام شما",
  failed: "خطا",
  understand: "درک نیازها",
  clarify: "پرسش‌های ضروری",
  build: "ساخت ربات",
  testgen: "ساخت آزمون‌ها",
  run: "اجرای آزمون‌ها",
  repair: "اصلاح خطاها",
  review: "بازبینی نهایی",
  await_approval: "انتظار برای تأیید شما",
  deploy: "فعال‌سازی",
};

/** Label for any phase name; a phase this client does not know gets a generic label, never an empty row. */
export function phaseLabel(phase: string): string {
  return (PHASE_LABELS as Record<string, string>)[phase] ?? "مرحلهٔ پردازش";
}

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  running: "در حال کار",
  waiting_user: "منتظر پاسخ شما",
  waiting_approval: "آمادهٔ تأیید",
  done: "انجام شد",
  failed: "ناموفق",
  rejected: "رد شد",
  interrupted: "قطع شد",
};

export const RUN_KIND_LABELS: Record<RunKind, string> = {
  create: "ساخت ربات",
  modify: "درخواست تغییر",
};

/** Label for any run kind; a kind this client does not know gets a generic label. */
export function runKindLabel(kind: string): string {
  return (RUN_KIND_LABELS as Record<string, string>)[kind] ?? "گفتگو با دستیار";
}

/** Headline of a failed run by error code; the server's own Persian message goes under it. */
export const FAILURE_TITLES: Record<ErrorCode, string> = {
  LLM_UNAVAILABLE: "دستیار نتوانست به مدل زبانی وصل شود",
  BUDGET_EXCEEDED: "سقف مصرف دستیار تمام شد",
  VALIDATION_FAILED: "ربات ساخته‌شده از بررسی درستی نگذشت",
  UNEXPECTED_ERROR: "کار دستیار با خطا روبه‌رو شد",
  INTERRUPTED: "کار دستیار وسط راه متوقف شد",
};

/** Owner-facing reason of an LLM retry; the raw reason string never shows. */
export function retryReasonLabel(reason: string): string {
  const r = reason.toLowerCase();
  if (r.includes("timeout") || r.includes("timed out")) return "پاسخ مدل دیر رسید";
  if (r.includes("rate") || r.includes("429") || r.includes("overload")) return "مدل شلوغ بود";
  if (r.includes("connect") || r.includes("network")) return "ارتباط با مدل ناپایدار بود";
  return "پاسخ مدل کامل نبود";
}

/** Plain-language type tags of a requirement. */
export const REQUIREMENT_KIND_LABELS: Record<RequirementKind, string> = {
  capability: "قابلیت",
  rule: "قاعده",
  data: "اطلاعات",
  text: "متن پیام‌ها",
  notification: "اطلاع‌رسانی",
};

/**
 * Owner-facing names of the agent's tool steps (D11). The raw tool name may only appear in the collapsed
 * «جزئیات فنی» section, never as the primary label.
 */
export const TOOL_LABELS: Record<string, string> = {
  set_spec: "نوشتن پیکربندی ربات",
  apply_spec_patch: "اعمال تغییر در پیکربندی",
  validate_spec: "بررسی درستی پیکربندی",
  get_spec: "خواندن پیکربندی",
  run_tests: "اجرای آزمون‌ها",
  get_failure: "بررسی آزمون ناموفق",
  fix_scenario: "اصلاح آزمون",
  supersede_scenario: "کنار گذاشتن آزمون قدیمی",
  finish: "آماده‌سازی نسخهٔ پیش‌نویس",
};

/** Label for any tool name; an unknown tool gets a generic label, never its raw name. */
export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? "گام فنی";
}

export const CAPABILITY_TYPE_LABELS: Record<CapabilityType, string> = {
  info: "اطلاعات",
  catalog: "فهرست",
  booking: "رزرو",
  request: "درخواست",
  orders: "سفارش‌ها",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  low: "ریسک کم",
  medium: "ریسک متوسط",
  high: "ریسک زیاد",
};
