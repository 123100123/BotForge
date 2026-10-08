import { ACCEPTANCE_TITLES, WORKSHOP_OUTLINE, workshopRequirements } from "./common";
import { ev, waitFor, type ScriptContext, type ScriptItem } from "./types";
import type { Question, Requirements } from "@/lib/types";

const CAPACITY_QUESTION: Question = {
  id: "Q1",
  text: "ظرفیت ۱۰ نفر برای همهٔ کارگاه‌ها یکسان است یا هر کارگاه ظرفیت جداگانه‌ای دارد؟",
  why: "اگر ظرفیت همه یکسان باشد، عدد آن در تنظیمات ربات ذخیره می‌شود و بعداً با یک جمله قابل تغییر است؛ در غیر این صورت ظرفیت را هنگام افزودن هر کارگاه وارد می‌کنید.",
  severity: "blocking",
  options: ["برای همهٔ کارگاه‌ها یکسان است (۱۰ نفر)", "هر کارگاه ظرفیت جداگانه دارد"],
};

/**
 * Recorded CREATE run for the golden workshop prompt. The owner's first message is emitted by the
 * mock server before this script starts. The script pauses at the clarification question
 * (wait "message") and at the approval request (wait "approve").
 */
export function createRunScript(ctx: ScriptContext): ScriptItem[] {
  const firstRound: Requirements = {
    ...workshopRequirements("ظرفیت هر کارگاه ۱۰ نفر است."),
    open_questions: [CAPACITY_QUESTION],
  };
  const secondRound: Requirements = workshopRequirements("ظرفیت همهٔ کارگاه‌ها یکسان و ۱۰ نفر است.");

  return [
    // --- understand (round 1) ---
    ev("phase_started", { phase: "understand" }, 500),
    ev("agent_message", { text: "توضیحاتتان را می‌خوانم و نیازمندی‌های ربات را استخراج می‌کنم." }, 700),
    ev("requirements", { requirements: firstRound }, 1400),
    ev("phase_finished", { phase: "understand", ok: true, summary: "۱۰ نیازمندی استخراج شد؛ یک پرسش ضروری باقی ماند" }, 500),

    // --- clarify ---
    ev("agent_message", { text: "برای ساختن درست ربات یک نکته را باید از شما بپرسم." }, 600),
    ev("questions", { questions: [CAPACITY_QUESTION] }, 400),
    waitFor("message"),

    // --- understand (round 2) ---
    ev("phase_started", { phase: "understand" }, 400),
    ev("requirements", { requirements: secondRound }, 1200),
    ev("phase_finished", { phase: "understand", ok: true, summary: "۱۰ نیازمندی نهایی شد؛ ۴ مورد فرض‌شده است" }, 500),
    ev("agent_message", { text: "ممنون. ربات را می‌سازم و بعد آن را آزمایش می‌کنم." }, 400),

    // --- build ---
    ev("phase_started", { phase: "build" }, 500),
    ev("tool_call", { loop: "build", name: "set_spec", summary: "نوشتن مشخصات ربات: یک قابلیت ثبت‌نام کارگاه، یک قابلیت اطلاعات و سه گزینهٔ منو" }, 1200),
    ev("tool_result", { name: "set_spec", ok: false, summary: "یک خطا: گزینهٔ منوی «دربارهٔ ما» به قابلیتی اشاره می‌کند که وجود ندارد" }, 900),
    ev("tool_call", { loop: "build", name: "apply_spec_patch", summary: "اتصال گزینهٔ منوی «دربارهٔ ما» به قابلیت اطلاعات" }, 800),
    ev("tool_result", { name: "apply_spec_patch", ok: true, summary: "یک تغییر اعمال شد" }, 700),
    ev("tool_call", { loop: "build", name: "validate_spec", summary: "اعتبارسنجی دوبارهٔ مشخصات" }, 600),
    ev("tool_result", { name: "validate_spec", ok: true, summary: "بدون خطا و بدون هشدار" }, 700),
    ev("spec_updated", { outline: WORKSHOP_OUTLINE }, 300),
    ev("tool_call", { loop: "build", name: "finish", summary: "پایان ساخت" }, 500),
    ev("tool_result", { name: "finish", ok: true, summary: "مشخصات ربات نهایی شد" }, 300),
    ev("phase_finished", { phase: "build", ok: true, summary: "ربات با دو قابلیت و سه گزینهٔ منو ساخته شد" }, 400),

    // --- testgen ---
    ev("phase_started", { phase: "testgen" }, 500),
    ev("tests_generated", { derived: 9, acceptance: 3 }, 1500),
    ev("phase_finished", { phase: "testgen", ok: true, summary: "۹ آزمون مشتق‌شده و ۳ آزمون پذیرش آماده شد" }, 400),

    // --- run (first attempt: one failure) ---
    ev("phase_started", { phase: "run" }, 500),
    ev(
      "test_report",
      {
        total: 12,
        passed: 11,
        failed: 1,
        failures: [
          {
            id: "acc_waitlist_promotion",
            title: ACCEPTANCE_TITLES.promotion,
            message: "مرحلهٔ ۶: انتظار می‌رفت ثبت‌نام رضا «تأییدشده» باشد، اما هنوز در «لیست انتظار» است.",
          },
        ],
      },
      1500,
    ),
    ev("phase_finished", { phase: "run", ok: false, summary: "۱۱ از ۱۲ آزمون موفق؛ ۱ آزمون ناموفق" }, 400),

    // --- repair ---
    ev("phase_started", { phase: "repair" }, 500),
    ev("tool_call", { loop: "repair", name: "get_failure", summary: "بررسی آزمون ناموفق «جایگزینی نفر اول لیست انتظار»" }, 900),
    ev("tool_result", { name: "get_failure", ok: true, summary: "ارتقای خودکار از لیست انتظار در مشخصات خاموش است" }, 800),
    ev("tool_call", { loop: "repair", name: "apply_spec_patch", summary: "روشن کردن ارتقای خودکار لیست انتظار" }, 900),
    ev("tool_result", { name: "apply_spec_patch", ok: true, summary: "یک تغییر اعمال شد" }, 700),
    ev("tool_call", { loop: "repair", name: "run_tests", summary: "اجرای دوبارهٔ همهٔ آزمون‌ها" }, 700),
    ev("tool_result", { name: "run_tests", ok: true, summary: "۱۲ از ۱۲ آزمون موفق" }, 900),
    ev("tool_call", { loop: "repair", name: "finish", summary: "پایان اصلاح" }, 400),
    ev("tool_result", { name: "finish", ok: true, summary: "اصلاح انجام شد" }, 300),
    ev("phase_finished", { phase: "repair", ok: true, summary: "یک مشکل در مشخصات برطرف شد" }, 400),

    // --- run (second attempt: green) ---
    ev("phase_started", { phase: "run" }, 500),
    ev("test_report", { total: 12, passed: 12, failed: 0, failures: [] }, 1300),
    ev("phase_finished", { phase: "run", ok: true, summary: "همهٔ ۱۲ آزمون موفق" }, 400),

    // --- review ---
    ev("phase_started", { phase: "review" }, 500),
    ev("usage", { input_tokens: 48210, output_tokens: 6120, cached_tokens: 31400, tool_calls: 9 }, 400),
    ev("phase_finished", { phase: "review", ok: true, summary: `خلاصهٔ نسخهٔ ${ctx.revisionNumber.toLocaleString("fa-IR")} آماده شد` }, 700),

    // --- await approval ---
    ev("agent_message", { text: "ربات ساخته و آزمایش شد. می‌توانید آن را در تب شبیه‌ساز امتحان کنید؛ اگر مورد تأیید بود، تأیید را بزنید تا فعال شود." }, 300),
    // The pause follows `approval_requested` immediately, so the approve button never shows before the run waits.
    ev("approval_requested", { revision_id: ctx.revisionId, can_approve: true }, 300),
    waitFor("approve"),

    // --- deploy ---
    ev("phase_started", { phase: "deploy" }, 400),
    ev("phase_finished", { phase: "deploy", ok: true, summary: `نسخهٔ ${ctx.revisionNumber.toLocaleString("fa-IR")} فعال شد` }, 1200),
    ev("agent_message", { text: "ربات فعال شد. حالا کارگاه‌های واقعی را اضافه کنید و ربات را به تلگرام وصل کنید." }, 300),
    // `deployed` is the last event of a run: once it arrives the run is done and a new one may start.
    ev("deployed", { revision_id: ctx.revisionId, number: ctx.revisionNumber }, 300),
  ];
}
