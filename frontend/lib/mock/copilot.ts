import type { CopilotMessageIn, CopilotMessageOut } from "@/lib/types";

/** Demo copilot: a deterministic answer that cites two "tool calls" and reports usage, so the ask-mode UI has everything to render. */
export function copilotMessage(body: CopilotMessageIn): CopilotMessageOut {
  const last = [...body.messages].reverse().find((m) => m.role === "user");
  return {
    reply: last
      ? `این یک پاسخ نمونه است. در حالت واقعی، دستیار با استفاده از داده‌های کسب‌وکار به «${last.content}» پاسخ می‌دهد.\nهفتهٔ گذشته 37 رزرو و 12 سفارش ثبت شده است و فروش نسبت به هفتهٔ قبل 8 درصد بیشتر بوده.`
      : "سؤال خود را دربارهٔ کسب‌وکارتان بپرسید.",
    tool_calls: [
      {
        name: "get_overview",
        arguments: { period: "7d", compare: true },
        summary: "نمای کلی هفتهٔ گذشته خوانده شد",
      },
      {
        name: "get_capability_report",
        arguments: { capability: "orders", period: "7d", metrics: ["orders_count", "revenue"] },
        summary: "گزارش سفارش‌ها خوانده شد",
      },
    ],
    usage: { input_tokens: 1240, output_tokens: 186, cost_usd: 0.0042 },
  };
}
