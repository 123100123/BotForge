import type { CapabilityType, Phase, RequirementKind, RiskLevel, RunKind, RunStatus } from "@/lib/types";

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
  waiting_approval: "منتظر تأیید شما",
  done: "انجام شد",
  failed: "ناموفق",
  rejected: "رد شد",
  interrupted: "قطع شد",
};

export const RUN_STATUS_VARIANT: Record<RunStatus, "accent" | "success" | "warning" | "destructive" | "secondary"> = {
  running: "accent",
  waiting_user: "warning",
  waiting_approval: "warning",
  done: "success",
  failed: "destructive",
  rejected: "secondary",
  interrupted: "destructive",
};

export const RUN_KIND_LABELS: Record<RunKind, string> = {
  create: "ساخت ربات",
  modify: "درخواست تغییر",
};

/** Label for any run kind; a kind this client does not know gets a generic label. */
export function runKindLabel(kind: string): string {
  return (RUN_KIND_LABELS as Record<string, string>)[kind] ?? "گفت‌وگو با ایجنت";
}

export const REQUIREMENT_KIND_LABELS: Record<RequirementKind, string> = {
  capability: "قابلیت",
  rule: "قانون",
  data: "داده",
  text: "متن",
  notification: "اعلان",
};

export const CAPABILITY_TYPE_LABELS: Record<CapabilityType, string> = {
  info: "اطلاعات",
  catalog: "فهرست",
  booking: "رزرو",
  request: "درخواست",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  low: "ریسک کم",
  medium: "ریسک متوسط",
  high: "ریسک زیاد",
};
