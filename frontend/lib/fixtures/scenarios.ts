import type {
  NoticeKind,
  Scenario,
  ScenarioResult,
  Step,
  StepResult,
  TestReport,
  TranscriptEntry,
} from "@/lib/types";

/**
 * A tiny DSL that produces, from one list of acts, the scenario steps (as the backend stores them),
 * the Persian narratives ("sentence ← result", as testing/drivers.py writes them) and a transcript.
 * Only used by the mock; shapes are exactly Scenario / ScenarioResult / TestReport.
 */

const NAMES: Record<string, string> = { ali: "علی", sara: "سارا", reza: "رضا", owner: "مدیر" };
const name = (who: string) => NAMES[who] ?? who;

const NOTICE_FA: Record<string, string> = {
  booked: "ثبت‌نام",
  waitlisted: "ورود به لیست انتظار",
  cancelled: "لغو",
  promoted: "جایگزینی از لیست انتظار",
  submitted: "ثبت درخواست",
  status_changed: "تغییر وضعیت",
};

export const ITEM = "کارگاه عکاسی";
const BOOK = "book_workshop";
const REQ = "repair";

export type Act =
  | { k: "open"; who: string }
  | { k: "book"; who: string; res: "confirmed" | "waitlisted" | "rejected" }
  | { k: "cancel"; who: string; res: "cancelled" | "rejected"; reason?: string }
  | { k: "owner_cancel"; target: string }
  | { k: "expect_booking"; who: string; res: "confirmed" | "waitlisted" | "cancelled" | "none" }
  | { k: "expect_counts"; confirmed: number; waitlisted: number }
  | { k: "notified"; who: string; event: NoticeKind }
  | { k: "advance"; hours: number }
  | { k: "submit"; who: string }
  | { k: "owner_action"; target: string; label: string; key: string; res: "ok" | "rejected" }
  | { k: "expect_request"; who: string; status: string; statusLabel: string };

const RES_FA: Record<string, string> = {
  confirmed: "تأیید شد",
  waitlisted: "در لیست انتظار قرار گرفت",
  rejected: "رد شد",
  cancelled: "لغو شد",
  none: "بدون ثبت‌نام",
  ok: "انجام شد",
};

const digits = (n: number) => n.toLocaleString("fa-IR");

function t(actor: string, direction: "in" | "out", text: string, buttons: string[] = []): TranscriptEntry {
  return { actor, direction, text, buttons };
}

interface Built {
  step: Step;
  sentence: string;
  result: string;
  transcript: TranscriptEntry[];
}

function build(a: Act): Built {
  switch (a.k) {
    case "open":
      return {
        step: { do: "open", actor: a.who, capability: BOOK, view: "main", contains: ITEM },
        sentence: `${name(a.who)} بخش «کارگاه‌ها و ثبت‌نام» را باز می‌کند`,
        result: "فهرست کارگاه‌ها نمایش داده شد",
        transcript: [
          t(a.who, "in", "کارگاه‌ها و ثبت‌نام"),
          t(a.who, "out", "کارگاه موردنظر را انتخاب کنید:", [ITEM, "بازگشت"]),
        ],
      };
    case "book": {
      const out =
        a.res === "confirmed"
          ? `ثبت‌نام شما در «${ITEM}» تأیید شد.`
          : a.res === "waitlisted"
            ? "ظرفیت این کارگاه تکمیل است؛ شما در لیست انتظار قرار گرفتید."
            : "شما قبلاً در این کارگاه ثبت‌نام کرده‌اید.";
      return {
        step: { do: "book", actor: a.who, capability: BOOK, item: "w1", expect: a.res },
        sentence: `${name(a.who)} در «${ITEM}» ثبت‌نام می‌کند`,
        result: a.res === "rejected" ? "رد شد (ثبت‌نام تکراری)" : RES_FA[a.res],
        transcript: [t(a.who, "in", "ثبت‌نام"), t(a.who, "out", out, ["لغو ثبت‌نام", "بازگشت"])],
      };
    }
    case "cancel":
      return {
        step: { do: "cancel", actor: a.who, capability: BOOK, item: "w1", expect: a.res },
        sentence: `${name(a.who)} ثبت‌نام خود در «${ITEM}» را لغو می‌کند`,
        result: a.res === "cancelled" ? "لغو شد" : `رد شد (${a.reason ?? "غیرمجاز"})`,
        transcript: [
          t(a.who, "in", "لغو ثبت‌نام"),
          t(a.who, "out", a.res === "cancelled" ? "ثبت‌نام شما لغو شد." : (a.reason ?? "لغو ممکن نیست.")),
        ],
      };
    case "owner_cancel":
      return {
        step: { do: "owner_action", actor: "owner", capability: BOOK, item: "w1", action: "cancel", target_actor: a.target, expect: "ok" },
        sentence: `مدیر ثبت‌نام ${name(a.target)} در «${ITEM}» را لغو می‌کند`,
        result: "انجام شد",
        transcript: [t("owner", "in", `لغو ثبت‌نام ${name(a.target)}`), t("owner", "out", "ثبت‌نام لغو شد.")],
      };
    case "expect_booking":
      return {
        step: { do: "expect_booking", actor: a.who, capability: BOOK, item: "w1", expect: a.res },
        sentence: `بررسی وضعیت ثبت‌نام ${name(a.who)} در «${ITEM}»`,
        result: a.res === "none" ? "ثبت‌نامی وجود ندارد" : RES_FA[a.res],
        transcript: [],
      };
    case "expect_counts":
      return {
        step: { do: "expect_counts", capability: BOOK, item: "w1", confirmed: a.confirmed, waitlisted: a.waitlisted },
        sentence: `بررسی تعداد ثبت‌نام‌های «${ITEM}»`,
        result: `${digits(a.confirmed)} تأییدشده، ${digits(a.waitlisted)} در لیست انتظار`,
        transcript: [],
      };
    case "notified":
      return {
        step: { do: "expect_notified", actor: a.who, event: a.event },
        sentence: `بررسی دریافت پیام «${NOTICE_FA[a.event]}» توسط ${name(a.who)}`,
        result: "پیام دریافت شد",
        transcript: [
          t(
            a.who,
            "out",
            a.event === "promoted"
              ? `جای شما در «${ITEM}» از لیست انتظار تأیید شد.`
              : a.event === "status_changed"
                ? "وضعیت درخواست شما تغییر کرد."
                : `ثبت‌نام جدید در «${ITEM}»`,
          ),
        ],
      };
    case "advance":
      return {
        step: { do: "advance_time", hours: a.hours },
        sentence: `${digits(a.hours)} ساعت می‌گذرد`,
        result: "",
        transcript: [],
      };
    case "submit":
      return {
        step: { do: "submit_request", actor: a.who, capability: REQ, expect: "submitted", form: [{ key: "device", value: "یخچال" }] },
        sentence: `${name(a.who)} در «درخواست تعمیر» درخواست ثبت می‌کند`,
        result: "ثبت شد",
        transcript: [
          t(a.who, "in", "ثبت درخواست تعمیر"),
          t(a.who, "out", "درخواست شما ثبت شد و پس از بررسی اطلاع می‌دهیم."),
          t("owner", "out", "درخواست تعمیر جدید: یخچال", ["تأیید", "رد"]),
        ],
      };
    case "owner_action":
      return {
        step: { do: "owner_action", actor: "owner", capability: REQ, action: a.key, target_actor: a.target, expect: a.res },
        sentence: `مدیر روی درخواست ${name(a.target)} در «درخواست تعمیر» اقدام «${a.label}» را انجام می‌دهد`,
        result: a.res === "ok" ? "انجام شد" : "رد شد",
        transcript: [t("owner", "in", a.label), t(a.target, "out", `وضعیت درخواست شما: ${a.label}`)],
      };
    case "expect_request":
      return {
        step: { do: "expect_request", actor: a.who, capability: REQ, expect: a.status },
        sentence: `بررسی وضعیت درخواست ${name(a.who)} در «درخواست تعمیر»`,
        result: a.statusLabel,
        transcript: [],
      };
  }
}

export interface ScenarioDef {
  id: string;
  title: string;
  source: "derived" | "acceptance";
  reqs?: string[];
  caps: string[];
  capacityOverride?: number | null;
  acts: Act[];
  /** Index of the step that fails (its message), making the scenario fail. */
  fail?: { at: number; message: string };
}

export function scenarioOf(def: ScenarioDef): Scenario {
  return {
    id: def.id,
    title: def.title,
    source: def.source,
    requirement_ids: def.reqs ?? [],
    capability_keys: def.caps,
    capacity_override: def.capacityOverride ?? null,
    seed: [
      {
        ref: "w1",
        collection: "workshop",
        values: [
          { key: "title", value: ITEM },
          { key: "starts_at", value: "+48h" },
        ],
      },
    ],
    steps: def.acts.map((a) => build(a).step),
  };
}

export function resultOf(def: ScenarioDef): ScenarioResult {
  const steps: StepResult[] = [];
  const transcript: TranscriptEntry[] = [];
  let failed: number | null = null;
  for (let i = 0; i < def.acts.length; i += 1) {
    const b = build(def.acts[i]);
    const isFail = def.fail?.at === i;
    steps.push({
      index: i,
      passed: !isFail,
      message: isFail ? def.fail!.message : null,
      narrative: isFail ? `${b.sentence} ← ناموفق` : b.result ? `${b.sentence} ← ${b.result}` : b.sentence,
    });
    // A failing step still produced the user's side of the conversation.
    transcript.push(...(isFail ? b.transcript.filter((e) => e.direction === "in") : b.transcript));
    if (isFail) {
      failed = i;
      break;
    }
  }
  return { scenario_id: def.id, passed: failed === null, failed_step: failed, steps, transcript };
}

export function reportOf(defs: ScenarioDef[]): TestReport {
  const results = defs.map(resultOf);
  const passed = results.filter((r) => r.passed).length;
  return { total: results.length, passed, failed: results.length - passed, results, duration_ms: 180 + defs.length * 7 };
}
