import type { CopilotMessageIn, CopilotMessageOut } from "@/lib/types";

/** Demo copilot: a canned answer that cites one "tool call", so the ask-mode UI has something to render. */
export function copilotMessage(body: CopilotMessageIn): CopilotMessageOut {
  const last = [...body.messages].reverse().find((m) => m.role === "user");
  return {
    reply: last
      ? `این یک پاسخ نمونه است. در حالت واقعی، دستیار با استفاده از داده‌های کسب‌وکار به «${last.content}» پاسخ می‌دهد. هفتهٔ گذشته ۳۷ رزرو و ۱۲ سفارش ثبت شده است.`
      : "سؤال خود را دربارهٔ کسب‌وکارتان بپرسید.",
    tool_calls: [
      {
        name: "get_overview",
        arguments: { period: "7d" },
        summary: "نمای کلی هفتهٔ گذشته خوانده شد",
      },
    ],
    usage: { input_tokens: 0, output_tokens: 0 },
  };
}
