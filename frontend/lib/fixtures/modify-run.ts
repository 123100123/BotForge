import { ACCEPTANCE_TITLES, WORKSHOP_OUTLINE, workshopRequirements } from "./common";
import { ev, waitFor, type ScriptContext, type ScriptItem } from "./types";

/**
 * Recorded MODIFY run for "capacity 10 -> 12" on the live workshop bot. The owner's message is
 * emitted by the mock server before this script starts. The script pauses at the approval request.
 */
export function modifyRunScript(ctx: ScriptContext): ScriptItem[] {
  const n = ctx.revisionNumber.toLocaleString("fa-IR");
  return [
    // --- triage (every run on a live bot starts here; a change request moves on) ---
    ev("phase_started", { phase: "triage" }, 400),
    ev("phase_finished", { phase: "triage", ok: true, summary: "درخواست تغییر ربات است" }, 700),

    // --- understand ---
    ev("phase_started", { phase: "understand" }, 400),
    ev("agent_message", { text: "درخواست تغییر را با نیازمندی‌ها و مشخصات فعلی ربات مقایسه می‌کنم." }, 700),
    ev("requirements", { requirements: workshopRequirements("ظرفیت همهٔ کارگاه‌ها یکسان و ۱۲ نفر است.") }, 1300),
    ev("phase_finished", { phase: "understand", ok: true, summary: "یک نیازمندی تغییر کرد: R3 (ظرفیت از ۱۰ به ۱۲)" }, 500),

    // --- build ---
    ev("phase_started", { phase: "build" }, 500),
    ev("tool_call", { loop: "build", name: "apply_spec_patch", summary: "تغییر ظرفیت قابلیت ثبت‌نام از ۱۰ به ۱۲ نفر" }, 1100),
    ev(
      "tool_result",
      { name: "apply_spec_patch", ok: true, summary: "یک تغییر اعمال شد:\nظرفیت: ۱۰ ← ۱۲\nسازگاری با داده‌های موجود تأیید شد" },
      800,
    ),
    ev("tool_call", { loop: "build", name: "validate_spec", summary: "اعتبارسنجی مشخصات جدید" }, 600),
    ev("tool_result", { name: "validate_spec", ok: true, summary: "بدون خطا و بدون هشدار" }, 700),
    ev("spec_updated", { outline: WORKSHOP_OUTLINE }, 300),
    ev("tool_call", { loop: "build", name: "finish", summary: "پایان اعمال تغییر" }, 500),
    ev("tool_result", { name: "finish", ok: true, summary: "پیش‌نویس نسخهٔ جدید آماده شد" }, 300),
    ev("phase_finished", { phase: "build", ok: true, summary: "یک پارامتر تغییر کرد" }, 400),

    // --- testgen ---
    ev("phase_started", { phase: "testgen" }, 500),
    ev(
      "tests_generated",
      {
        derived: 9,
        acceptance: 1,
        notes: ["آزمون «ظرفیت واقعی ۱۰ نفر» به نیازمندی تغییرکرده R3 وابسته است و دوباره نوشته شد."],
      },
      1300,
    ),
    ev("phase_finished", { phase: "testgen", ok: true, summary: "آزمون‌های مشتق‌شده دوباره ساخته شد؛ ۳ آزمون پذیرش قبلی منتقل و ۱ آزمون جدید نوشته شد" }, 400),

    // --- run (first attempt: the capacity-10 scenario fails) ---
    ev("phase_started", { phase: "run" }, 500),
    ev(
      "test_report",
      {
        total: 13,
        passed: 12,
        failed: 1,
        failures: [
          {
            id: "acc_capacity_ten",
            title: ACCEPTANCE_TITLES.capacity,
            message: "مرحلهٔ ۱۲: انتظار می‌رفت ثبت‌نام نفر یازدهم «لیست انتظار» باشد، اما «تأییدشده» ثبت شد.",
          },
        ],
      },
      1400,
    ),
    ev("phase_finished", { phase: "run", ok: false, summary: "۱۲ از ۱۳ آزمون موفق؛ ۱ آزمون ناموفق" }, 400),

    // --- repair ---
    ev("phase_started", { phase: "repair" }, 500),
    ev("tool_call", { loop: "repair", name: "supersede_scenario", summary: "کنار گذاشتن آزمون «ظرفیت ۱۰ نفر» چون به نیازمندی تغییرکرده R3 وابسته است" }, 1000),
    ev("tool_result", { name: "supersede_scenario", ok: true, summary: "آزمون با آزمون جدید ظرفیت ۱۲ نفر جایگزین شد" }, 800),
    ev("tool_call", { loop: "repair", name: "run_tests", summary: "اجرای دوبارهٔ همهٔ آزمون‌ها" }, 700),
    ev("tool_result", { name: "run_tests", ok: true, summary: "۱۲ از ۱۲ آزمون موفق" }, 900),
    ev("tool_call", { loop: "repair", name: "finish", summary: "پایان اصلاح" }, 400),
    ev("tool_result", { name: "finish", ok: true, summary: "اصلاح انجام شد" }, 300),
    ev("phase_finished", { phase: "repair", ok: true, summary: "یک آزمون قدیمی با دلیل کنار گذاشته شد" }, 400),

    // --- run (second attempt: green) ---
    ev("phase_started", { phase: "run" }, 500),
    ev("test_report", { total: 12, passed: 12, failed: 0, failures: [] }, 1200),
    ev("phase_finished", { phase: "run", ok: true, summary: "همهٔ ۱۲ آزمون موفق" }, 400),

    // --- review ---
    ev("phase_started", { phase: "review" }, 500),
    ev(
      "diff",
      {
        changes: [{ label_fa: "ظرفیت هر کارگاه: ۱۰ ← ۱۲", kind: "changed" }],
        affected_capabilities: ["book_workshop"],
        tests: {
          carried: [
            { title: ACCEPTANCE_TITLES.basic, reason: "به نیازمندی تغییرکرده وابسته نیست؛ بدون تغییر منتقل شد" },
            { title: ACCEPTANCE_TITLES.promotion, reason: "با ظرفیت ۲ اجرا می‌شود و به عدد ظرفیت وابسته نیست" },
          ],
          new: [
            { title: "ظرفیت ۱۲ نفر پر می‌شود و نفر سیزدهم در لیست انتظار قرار می‌گیرد", reason: "برای نیازمندی R3 (ظرفیت ۱۲ نفر)" },
          ],
          superseded: [
            { title: ACCEPTANCE_TITLES.capacity, reason: "مربوط به ظرفیت قبلی (۱۰ نفر) بود و نیازمندی R3 تغییر کرده است" },
          ],
        },
        risk: "low",
        warnings: [],
        requirements: {
          added: [],
          changed: [
            {
              id: "R3",
              before: "ظرفیت همهٔ کارگاه‌ها یکسان و ۱۰ نفر است.",
              after: "ظرفیت همهٔ کارگاه‌ها یکسان و ۱۲ نفر است.",
            },
          ],
          removed: [],
        },
      },
      900,
    ),
    ev("usage", { input_tokens: 21840, output_tokens: 2310, cached_tokens: 17900, tool_calls: 5 }, 300),
    ev("phase_finished", { phase: "review", ok: true, summary: "مقایسهٔ نسخه‌ها و آزمون‌ها آماده شد" }, 500),

    // --- await approval ---
    ev("agent_message", { text: "تغییر اعمال و آزمایش شد. ربات فعلی تا وقتی تأیید نکنید تغییری نمی‌کند." }, 300),
    // The pause follows `approval_requested` immediately, so the approve button never shows before the run waits.
    ev("approval_requested", { revision_id: ctx.revisionId, can_approve: true }, 300),
    waitFor("approve"),

    // --- deploy ---
    ev("phase_started", { phase: "deploy" }, 400),
    ev("phase_finished", { phase: "deploy", ok: true, summary: `نسخهٔ ${n} فعال شد` }, 1000),
    ev("agent_message", { text: `نسخهٔ ${n} روی همان ربات فعال شد؛ ظرفیت هر کارگاه از همین حالا ۱۲ نفر است.` }, 300),
    // `deployed` is the last event of a run: once it arrives the run is done and a new one may start.
    ev("deployed", { revision_id: ctx.revisionId, number: ctx.revisionNumber }, 300),
  ];
}
