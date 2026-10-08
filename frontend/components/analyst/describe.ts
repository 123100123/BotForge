import { fa, formatNumber } from "@/lib/format";
import type { AnalysisCheckSpec, AnalysisMetricSpec } from "@/lib/types";

/** Plain sentences for what a profile measures and checks, so an owner never has to read a spec. */

const MEASURE_WORD: Record<AnalysisMetricSpec["measure"], string> = {
  count: "تعداد",
  sum: "جمع",
  avg: "میانگین",
  min: "کمترین",
  max: "بیشترین",
};

/** «جمع مبلغ به تفکیک محصول، ۵ مورد برتر» / «تعداد ردیف‌ها به تفکیک روز». */
export function metricSentence(m: AnalysisMetricSpec): string {
  const what = m.measure === "count" && !m.field ? "تعداد ردیف‌ها" : `${MEASURE_WORD[m.measure]} ${m.field ?? "ردیف‌ها"}`;
  let by = "";
  if (m.group_by) {
    if (m.group_kind === "day") by = " به تفکیک روز";
    else if (m.group_kind === "week") by = " به تفکیک هفته";
    else by = ` به تفکیک ${m.group_by}`;
  }
  const top = m.top_n ? `، ${fa(m.top_n)} مورد برتر` : "";
  return `${what}${by}${top}`;
}

/** «هشدار وقتی مبلغ از حد معمول بالاتر باشد» / «هشدار برای خانه‌های خالی در ستون نام». */
export function checkSentence(c: AnalysisCheckSpec): string {
  const by = c.group_by ? `، به تفکیک ${c.group_by}` : "";
  const limit = c.threshold === null ? "حد تعیین‌شده" : formatNumber(c.threshold);
  switch (c.kind) {
    case "outlier_high":
      return `هشدار وقتی ${c.field} از حد معمول بالاتر باشد${by}`;
    case "outlier_low":
      return `هشدار وقتی ${c.field} از حد معمول پایین‌تر باشد${by}`;
    case "threshold_above":
      return `هشدار وقتی ${c.field} از ${limit} بیشتر شود${by}`;
    case "threshold_below":
      return `هشدار وقتی ${c.field} از ${limit} کمتر شود${by}`;
    case "missing_values":
      return `هشدار برای خانه‌های خالی در ستون ${c.field}${by}`;
  }
}
