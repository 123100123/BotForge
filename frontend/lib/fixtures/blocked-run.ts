import { WORKSHOP_OUTLINE, workshopRequirements } from "./common";
import { ev, waitFor, type ScriptContext, type ScriptItem } from "./types";
import type { Requirements } from "@/lib/types";

const FAILING_TITLE = "پرداخت آنلاین هزینهٔ ثبت‌نام انجام می‌شود";

/**
 * Recorded MODIFY run for a request the product cannot fully do ("pay for the workshop online"; the
 * mock picks it when the owner's message contains «پرداخت»). It exercises two states of the Agent tab:
 * an `unsupported` requirement with an alternative, and `approval_requested` with `can_approve: false`.
 * The owner can only reject it.
 */
export function blockedRunScript(ctx: ScriptContext): ScriptItem[] {
  const base = workshopRequirements("ظرفیت همهٔ کارگاه‌ها یکسان و ۱۲ نفر است.");
  const requirements: Requirements = {
    ...base,
    items: [
      ...base.items,
      { id: "R11", kind: "rule", statement: "هزینهٔ کارگاه هنگام ثبت‌نام در ربات نمایش داده می‌شود.", status: "assumed" },
    ],
    unsupported: [
      {
        statement: "پرداخت آنلاین هزینهٔ ثبت‌نام از داخل ربات",
        reason: "ربات‌هایی که اینجا ساخته می‌شوند به درگاه پرداخت وصل نمی‌شوند.",
        alternative: "هزینهٔ هر کارگاه در جزئیات آن نمایش داده شود و پرداخت خارج از ربات (مثلاً کارت‌به‌کارت) انجام شود.",
      },
    ],
  };

  return [
    ev("phase_started", { phase: "triage" }, 400),
    ev("phase_finished", { phase: "triage", ok: true, summary: "درخواست تغییر ربات است" }, 700),
    ev("phase_started", { phase: "understand" }, 400),
    ev("agent_message", { text: "درخواست شما را با قابلیت‌های فعلی بررسی می‌کنم." }, 700),
    ev("requirements", { requirements }, 1300),
    ev("phase_finished", { phase: "understand", ok: true, summary: "یک مورد از درخواست قابل انجام نیست؛ بقیه فرض‌های قبلی حفظ شد" }, 500),

    ev("phase_started", { phase: "build" }, 500),
    ev("tool_call", { loop: "build", name: "apply_spec_patch", summary: "نمایش هزینه در جزئیات کارگاه" }, 1000),
    ev("tool_result", { name: "apply_spec_patch", ok: true, summary: "یک تغییر اعمال شد" }, 700),
    ev("spec_updated", { outline: WORKSHOP_OUTLINE }, 300),
    ev("phase_finished", { phase: "build", ok: true, summary: "تنها بخش قابل انجام اعمال شد" }, 400),

    ev("phase_started", { phase: "testgen" }, 500),
    ev("tests_generated", { derived: 9, acceptance: 4 }, 1200),
    ev("phase_finished", { phase: "testgen", ok: true, summary: "۹ آزمون مشتق‌شده و ۴ آزمون پذیرش آماده شد" }, 400),

    ev("phase_started", { phase: "run" }, 500),
    ev(
      "test_report",
      {
        total: 13,
        passed: 12,
        failed: 1,
        failures: [
          {
            id: "acc_online_payment",
            title: FAILING_TITLE,
            message: "مرحلهٔ ۳: دکمهٔ «پرداخت» در پیام ربات پیدا نشد؛ ربات قابلیت پرداخت ندارد.",
          },
        ],
      },
      1300,
    ),
    ev("phase_finished", { phase: "run", ok: false, summary: "۱۲ از ۱۳ آزمون موفق؛ ۱ آزمون ناموفق" }, 400),

    ev("phase_started", { phase: "repair" }, 500),
    ev("tool_call", { loop: "repair", name: "get_failure", summary: "بررسی آزمون ناموفق «پرداخت آنلاین»" }, 900),
    ev("tool_result", { name: "get_failure", ok: true, summary: "آزمون به قابلیتی وابسته است که پشتیبانی نمی‌شود" }, 800),
    ev("phase_finished", { phase: "repair", ok: false, summary: "آزمون ناموفق با تغییر مشخصات قابل رفع نیست" }, 500),

    ev("phase_started", { phase: "review" }, 500),
    ev(
      "diff",
      {
        changes: [{ label_fa: "ثبت‌نام در کارگاه — جزئیات کارگاه: هزینه نمایش داده می‌شود", kind: "changed" }],
        affected_capabilities: ["book_workshop"],
        tests: { carried: 12, new: 1, superseded: 0 },
        risk: "low",
        warnings: ["یک آزمون ناموفق است و تا رفع آن امکان تأیید وجود ندارد."],
      },
      900,
    ),
    ev("phase_finished", { phase: "review", ok: true, summary: "بازبینی آماده شد" }, 400),

    ev("agent_message", { text: "این تغییر کامل انجام نشد و قابل تأیید نیست. می‌توانید آن را رد کنید و درخواست را بدون بخش پرداخت دوباره بنویسید." }, 300),
    ev(
      "approval_requested",
      {
        revision_id: ctx.revisionId,
        can_approve: false,
        blocked_reason: "یک آزمون هنوز ناموفق است؛ تا برطرف شدن آن تأیید این نسخه ممکن نیست.",
      },
      300,
    ),
    waitFor("approve"),
  ];
}
