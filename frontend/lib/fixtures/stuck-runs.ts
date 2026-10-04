import { ev, waitFor, type ScriptItem } from "./types";

/**
 * Triage run: on a live bot a question or data request is answered with a plain message and the run
 * ends `done` without a revision. The only events are `phase_*`, an `agent_message` and `run_status`
 * (the mock picks this script for a message containing «چند»).
 */
export function triageRunScript(): ScriptItem[] {
  return [
    ev("phase_started", { phase: "triage" }, 500),
    ev(
      "agent_message",
      {
        text: "الان ۱۸ ثبت‌نام فعال دارید: ۱۲ نفر تأییدشده و ۲ نفر در لیست انتظار «کارگاه عکاسی با موبایل». برای دیدن فهرست کامل به تب «داده‌ها» بروید.",
      },
      900,
    ),
    ev("phase_finished", { phase: "triage", ok: true }, 400),
  ];
}

/**
 * A run that pauses for the owner without a `questions` event: the agent asks in plain text and the
 * run waits (`waiting_user`). The mock picks it for a message containing «پیامک».
 */
export function plainWaitRunScript(): ScriptItem[] {
  return [
    ev("phase_started", { phase: "triage" }, 500),
    ev("agent_message", { text: "برای ارسال پیامک باید بدانم پیامک به مشتری برود یا به شما؟ لطفاً پاسخ دهید." }, 800),
    waitFor("message"),
    ev("agent_message", { text: "ممنون. فعلاً ربات پیامک ارسال نمی‌کند؛ اعلان‌ها فقط در تلگرام ارسال می‌شود. اگر تغییر دیگری می‌خواهید بنویسید." }, 700),
    ev("phase_finished", { phase: "triage", ok: true }, 400),
  ];
}
