import type { CapabilityOut, ToolCallOut } from "@/lib/types";

/**
 * What the assistant looked at, in the owner's words. Tool names, arguments, tokens and cost are never shown;
 * an unknown tool falls back to a generic phrase.
 */
const TOOL_SOURCES: Record<string, { label: string; report: boolean }> = {
  get_business_summary: { label: "نمای کلی کسب‌وکار", report: true },
  get_overview: { label: "نمای کلی کسب‌وکار", report: true },
  get_capability_report: { label: "گزارش قابلیت‌ها", report: true },
  compare_periods: { label: "مقایسهٔ دوره‌ها", report: true },
  list_pending_approvals: { label: "درخواست‌های منتظر تأیید", report: false },
  get_spreadsheet_report: { label: "تحلیل فایل اکسل", report: false },
  who_submitted: { label: "فهرست ارسال گزارش‌ها", report: false },
};

export interface AnswerSources {
  /** Distinct Persian labels, in the order the tools were used. */
  labels: string[];
  /** A report or overview tool was used, so /reports shows the same numbers. */
  hasReport: boolean;
}

export function answerSources(calls: ToolCallOut[] | undefined): AnswerSources {
  const labels: string[] = [];
  let hasReport = false;
  for (const call of calls ?? []) {
    const known = TOOL_SOURCES[call.name];
    const label = known?.label ?? "داده‌های کسب‌وکار";
    if (!labels.includes(label)) labels.push(label);
    if (known?.report) hasReport = true;
  }
  return { labels, hasReport };
}

/** Question chips for the Overview and the assistant's empty state, built from what the business has switched on. */
export function suggestedQuestions(capabilities: CapabilityOut[]): string[] {
  const on = (id: string) => capabilities.some((c) => c.id === id && c.enabled);
  const picks: string[] = [];
  if (on("orders")) picks.push("فروش این هفته چطور بود؟");
  if (on("events")) picks.push("فردا چه رویدادهایی داریم؟");
  if (on("staff_reporting") || on("spreadsheet_intelligence")) picks.push("چه کسی گزارش امروز را نفرستاده؟");
  if (on("booking")) picks.push("کدام خدمت بیشترین رزرو را داشته؟");
  for (const generic of ["این هفته چه اتفاقی افتاده؟", "چه چیزی منتظر تأیید من است؟", "مهم‌ترین تغییرات این هفته چه بود؟"]) {
    if (picks.length >= 3) break;
    picks.push(generic);
  }
  return picks.slice(0, 3);
}
