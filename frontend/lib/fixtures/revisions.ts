import { workshopRequirements } from "./common";
import { reportOf, scenarioOf, type Act, type ScenarioDef } from "./scenarios";
import { repairSpec, workshopSpec } from "./specs";
import type { BotSpec, Requirements, RevisionDetail, RevisionStatus, SpecChange, TestCounts } from "@/lib/types";

/** Which fixture content a mock revision carries. */
export type RevisionVariant = "initial" | "cap12" | "deadline2" | "repair" | "repair_failing" | "legacy";

export interface StoredRevision {
  id: string;
  bot_id: string;
  number: number;
  parent_id: string | null;
  status: RevisionStatus;
  change_request: string | null;
  created_at: string;
  activated_at: string | null;
  variant: RevisionVariant;
  /**
   * "legacy" revisions are stored without scenarios or a report (scenarios null); running the tests
   * derives them, as the real backend does, and sets this flag.
   */
  ran?: boolean;
}

const CAP_LABEL = "ثبت‌نام در کارگاه — ";

function capacityOf(v: RevisionVariant): number {
  return v === "initial" || v === "legacy" ? 10 : 12;
}

/** True while a legacy revision has nothing stored. */
export function hasNoStoredTests(rev: StoredRevision): boolean {
  return rev.variant === "legacy" && !rev.ran;
}

/* ------------------------------------------------------------------ workshop scenarios */

const book = (who: string, res: "confirmed" | "waitlisted" | "rejected" = "confirmed"): Act => ({ k: "book", who, res });

function realCapacityActs(n: number): Act[] {
  const acts: Act[] = [];
  for (let i = 1; i <= n; i += 1) acts.push(book(`u${i}`));
  acts.push(book(`u${n + 1}`, "waitlisted"));
  acts.push({ k: "expect_counts", confirmed: n, waitlisted: 1 });
  return acts;
}

function workshopDefs(v: RevisionVariant): ScenarioDef[] {
  const cap = capacityOf(v);
  const capFa = cap.toLocaleString("fa-IR");
  const caps = ["book_workshop"];
  const defs: ScenarioDef[] = [
    { id: "d_book_basic", title: "ثبت‌نام ساده و مشاهدهٔ ثبت‌نام‌های من", source: "derived", caps, capacityOverride: 2,
      acts: [{ k: "open", who: "ali" }, book("ali"), { k: "expect_booking", who: "ali", res: "confirmed" }] },
    { id: "d_capacity_reached", title: "تکمیل ظرفیت: نفر بعد از پر شدن ظرفیت در لیست انتظار قرار می‌گیرد", source: "derived", caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "expect_counts", confirmed: 2, waitlisted: 1 }] },
    { id: "d_duplicate", title: "ثبت‌نام تکراری در یک کارگاه رد می‌شود", source: "derived", caps, capacityOverride: 2,
      acts: [book("ali"), book("ali", "rejected")] },
    { id: "d_cancel_frees", title: "لغو ثبت‌نام یک جا را آزاد می‌کند", source: "derived", caps, capacityOverride: 2,
      acts: [book("ali"), { k: "cancel", who: "ali", res: "cancelled" }, { k: "expect_counts", confirmed: 0, waitlisted: 0 }] },
    { id: "d_promotion_order", title: "جایگزینی از لیست انتظار به ترتیب ورود انجام می‌شود", source: "derived", caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "cancel", who: "ali", res: "cancelled" }, { k: "expect_booking", who: "reza", res: "confirmed" }] },
    { id: "d_capacity_real", title: `ظرفیت پیکربندی‌شده: ${capFa} نفر تأیید می‌شوند و نفر بعدی در لیست انتظار قرار می‌گیرد`, source: "derived", caps,
      acts: realCapacityActs(cap) },
    { id: "d_owner_notified", title: "مدیر از هر ثبت‌نام جدید مطلع می‌شود", source: "derived", caps, capacityOverride: 2,
      acts: [book("ali"), { k: "notified", who: "owner", event: "booked" }] },
    { id: "d_catalog_open", title: "فهرست کارگاه‌ها نمایش داده می‌شود", source: "derived", caps: ["workshop"],
      acts: [{ k: "open", who: "sara" }] },
    { id: "d_info_open", title: "بخش «دربارهٔ ما» نمایش داده می‌شود", source: "derived", caps: ["info"],
      acts: [{ k: "open", who: "reza" }] },
  ];

  if (v === "deadline2") {
    defs.push(
      { id: "d_deadline_before", title: "لغو تا ۲ ساعت قبل از شروع ممکن است", source: "derived", caps, capacityOverride: 2,
        acts: [book("ali"), { k: "advance", hours: 45 }, { k: "cancel", who: "ali", res: "cancelled" }] },
      { id: "d_deadline_after", title: "لغو کمتر از ۲ ساعت مانده به شروع رد می‌شود", source: "derived", caps, capacityOverride: 2,
        acts: [book("ali"), { k: "advance", hours: 47 }, { k: "cancel", who: "ali", res: "rejected", reason: "مهلت لغو گذشته است" }] },
    );
  }

  const acc: ScenarioDef[] = [
    { id: "golden_basic_book", title: "ثبت‌نام ساده: علی کارگاه را می‌بیند، ثبت‌نام می‌کند و مدیر مطلع می‌شود", source: "acceptance", reqs: ["R1", "R7"], caps, capacityOverride: 2,
      acts: [{ k: "open", who: "ali" }, book("ali"), { k: "expect_booking", who: "ali", res: "confirmed" }, { k: "expect_counts", confirmed: 1, waitlisted: 0 }, { k: "notified", who: "owner", event: "booked" }] },
    cap === 10
      ? { id: "golden_capacity_10_real", title: "ظرفیت واقعی ۱۰ نفر: ده نفر تأیید می‌شوند و نفر یازدهم به لیست انتظار می‌رود", source: "acceptance", reqs: ["R3"], caps, acts: realCapacityActs(10) }
      : { id: "golden_capacity_12_real", title: "ظرفیت واقعی ۱۲ نفر: دوازده نفر تأیید می‌شوند و نفر سیزدهم به لیست انتظار می‌رود", source: "acceptance", reqs: ["R3"], caps, acts: realCapacityActs(12) },
    { id: "golden_capacity_waitlist", title: "ظرفیت ۲: علی و سارا تأیید می‌شوند و رضا وارد لیست انتظار می‌شود", source: "acceptance", reqs: ["R3"], caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "expect_counts", confirmed: 2, waitlisted: 1 }, { k: "expect_booking", who: "reza", res: "waitlisted" }] },
    { id: "golden_duplicate_rejected", title: "ثبت‌نام تکراری: علی نمی‌تواند دو بار در یک کارگاه ثبت‌نام کند", source: "acceptance", reqs: ["R6"], caps, capacityOverride: 2,
      acts: [book("ali"), book("ali", "rejected"), { k: "expect_counts", confirmed: 1, waitlisted: 0 }] },
    { id: "golden_cancel_frees_seat", title: "لغو ثبت‌نام جا را آزاد می‌کند: علی لغو می‌کند و رضا تأیید می‌شود", source: "acceptance", reqs: ["R5", "R7"], caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "cancel", who: "ali", res: "cancelled" }, { k: "expect_booking", who: "ali", res: "cancelled" }, { k: "expect_booking", who: "reza", res: "confirmed" }, { k: "expect_counts", confirmed: 2, waitlisted: 0 }] },
    { id: "golden_promotion_order", title: "جایگزینی خودکار به ترتیب: با لغو علی، رضا (اولین نفر لیست انتظار) تأیید می‌شود", source: "acceptance", reqs: ["R4"], caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "cancel", who: "ali", res: "cancelled" }, { k: "expect_booking", who: "reza", res: "confirmed" }] },
    { id: "golden_waitlisted_cancel_no_promotion", title: "لغو توسط نفر لیست انتظار کسی را جایگزین نمی‌کند", source: "acceptance", reqs: ["R4", "R5"], caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "cancel", who: "reza", res: "cancelled" }, { k: "expect_counts", confirmed: 2, waitlisted: 0 }] },
    { id: "golden_promotion_notifies", title: "اطلاع‌رسانی جایگزینی: رضا پس از تأیید از لیست انتظار پیام می‌گیرد", source: "acceptance", reqs: ["R4"], caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "cancel", who: "ali", res: "cancelled" }, { k: "notified", who: "reza", event: "promoted" }] },
    { id: "golden_owner_cancel_promotes", title: "لغو توسط مدیر: مدیر ثبت‌نام علی را لغو می‌کند و رضا از لیست انتظار جایگزین می‌شود", source: "acceptance", reqs: ["R4"], caps, capacityOverride: 2,
      acts: [book("ali"), book("sara"), book("reza", "waitlisted"), { k: "owner_cancel", target: "ali" }, { k: "expect_booking", who: "reza", res: "confirmed" }] },
  ];
  if (v === "deadline2") {
    acc.push({
      id: "acc_cancel_deadline", title: "لغو فقط تا ۲ ساعت قبل از شروع: علی نزدیک شروع کارگاه نمی‌تواند لغو کند", source: "acceptance", reqs: ["R11"], caps, capacityOverride: 2,
      acts: [book("ali"), { k: "advance", hours: 47 }, { k: "cancel", who: "ali", res: "rejected", reason: "مهلت لغو گذشته است" }, { k: "expect_booking", who: "ali", res: "confirmed" }],
    });
  }
  return [...defs, ...acc];
}

/* ------------------------------------------------------------------ repair scenarios */

function repairDefs(failing: boolean): ScenarioDef[] {
  const caps = ["repair"];
  const defs: ScenarioDef[] = [
    { id: "d_submit_track", title: "ثبت درخواست و پیگیری آن", source: "derived", caps,
      acts: [{ k: "submit", who: "ali" }, { k: "expect_request", who: "ali", status: "new", statusLabel: "در انتظار بررسی" }] },
    { id: "d_approve", title: "تأیید درخواست توسط مدیر", source: "derived", caps,
      acts: [{ k: "submit", who: "ali" }, { k: "owner_action", target: "ali", label: "تأیید", key: "approve", res: "ok" }, { k: "expect_request", who: "ali", status: "approved", statusLabel: "تأیید شده" }] },
    { id: "d_reject", title: "رد درخواست توسط مدیر", source: "derived", caps,
      acts: [{ k: "submit", who: "sara" }, { k: "owner_action", target: "sara", label: "رد", key: "reject", res: "ok" }, { k: "expect_request", who: "sara", status: "rejected", statusLabel: "رد شده" }] },
    { id: "d_invalid_action", title: "اقدام «انجام شد» روی درخواست جدید رد می‌شود", source: "derived", caps,
      acts: [{ k: "submit", who: "reza" }, { k: "owner_action", target: "reza", label: "انجام شد", key: "mark_done", res: "rejected" }] },
    { id: "d_notify_user", title: "تغییر وضعیت به مشتری اطلاع داده می‌شود", source: "derived", caps,
      acts: [{ k: "submit", who: "ali" }, { k: "owner_action", target: "ali", label: "تأیید", key: "approve", res: "ok" }, { k: "notified", who: "ali", event: "status_changed" }] },
    { id: "acc_owner_alert", title: "مدیر از ثبت درخواست جدید مطلع می‌شود", source: "acceptance", reqs: ["R1"], caps,
      acts: [{ k: "submit", who: "ali" }, { k: "notified", who: "owner", event: "submitted" }] },
    { id: "acc_approve_flow", title: "درخواست پس از تأیید مدیر «تأیید شده» می‌شود", source: "acceptance", reqs: ["R2"], caps,
      acts: [{ k: "submit", who: "sara" }, { k: "owner_action", target: "sara", label: "تأیید", key: "approve", res: "ok" }, { k: "expect_request", who: "sara", status: "approved", statusLabel: "تأیید شده" }] },
  ];
  if (failing) {
    defs.push({
      id: "acc_assign_technician",
      title: "مدیر درخواست تأییدشده را به تکنسین ارجاع می‌دهد",
      source: "acceptance",
      reqs: ["R3"],
      caps,
      acts: [
        { k: "submit", who: "ali" },
        { k: "owner_action", target: "ali", label: "تأیید", key: "approve", res: "ok" },
        { k: "owner_action", target: "ali", label: "ارجاع به تکنسین", key: "assign", res: "ok" },
        { k: "expect_request", who: "ali", status: "assigned", statusLabel: "ارجاع به تکنسین" },
      ],
      fail: { at: 2, message: "دکمهٔ «ارجاع به تکنسین» در پیام مدیر پیدا نشد؛ پس از تأیید فقط دکمهٔ «انجام شد» نمایش داده می‌شود." },
    });
  }
  return defs;
}

/* ------------------------------------------------------------------ requirements, diffs */

function requirementsOf(v: RevisionVariant): Requirements {
  if (v === "repair" || v === "repair_failing") {
    return {
      business_summary: "خدمات تعمیر لوازم خانگی که درخواست‌ها را از طریق ربات می‌گیرد و مدیر هر درخواست را تأیید یا رد می‌کند.",
      items: [
        { id: "R1", kind: "notification", statement: "با ثبت هر درخواست، مدیر در تلگرام مطلع می‌شود.", status: "confirmed" },
        { id: "R2", kind: "rule", statement: "مدیر می‌تواند درخواست را تأیید یا رد کند.", status: "confirmed" },
        ...(v === "repair_failing"
          ? ([{ id: "R3", kind: "rule", statement: "مدیر می‌تواند درخواست تأییدشده را به تکنسین ارجاع دهد.", status: "confirmed" }] as const)
          : []),
      ],
      unsupported: [],
      open_questions: [],
    };
  }
  const capacity = capacityOf(v) === 10 ? "ظرفیت همهٔ کارگاه‌ها یکسان و ۱۰ نفر است." : "ظرفیت همهٔ کارگاه‌ها یکسان و ۱۲ نفر است.";
  const base = workshopRequirements(capacity);
  if (v === "deadline2") {
    base.items.push({ id: "R11", kind: "rule", statement: "لغو ثبت‌نام فقط تا ۲ ساعت قبل از شروع کارگاه ممکن است.", status: "confirmed" });
  }
  return base;
}

const DIFF_CAP12: SpecChange[] = [
  { path: ["capabilities", "book_workshop", "capacity", "value"], kind: "changed", old: 10, new: 12, label_fa: `${CAP_LABEL}ظرفیت: ۱۰ ← ۱۲` },
];
const DIFF_DEADLINE: SpecChange[] = [
  { path: ["capabilities", "book_workshop", "cancellation", "deadline_hours"], kind: "changed", old: null, new: 2, label_fa: `${CAP_LABEL}مهلت لغو ثبت‌نام: بدون محدودیت ← تا ۲ ساعت قبل از شروع` },
];
const DIFF_ASSIGN: SpecChange[] = [
  { path: ["capabilities", "repair", "statuses", "assigned"], kind: "added", old: null, new: { key: "assigned", label: "ارجاع به تکنسین" }, label_fa: "درخواست تعمیر — افزوده شد: وضعیت «ارجاع به تکنسین»" },
  { path: ["capabilities", "repair", "owner_actions", "assign"], kind: "added", old: null, new: { key: "assign", label: "ارجاع به تکنسین" }, label_fa: "درخواست تعمیر — افزوده شد: اقدام مدیر «ارجاع به تکنسین»" },
  { path: ["capabilities", "repair", "owner_actions", "mark_done", "from_statuses"], kind: "changed", old: ["approved"], new: ["approved", "assigned"], label_fa: "درخواست تعمیر — اقدام «انجام شد» — وضعیت‌های مبدأ: «تأیید شده» ← «تأیید شده»، «ارجاع به تکنسین»" },
];

function diffOf(v: RevisionVariant): SpecChange[] {
  if (v === "cap12") return DIFF_CAP12;
  if (v === "deadline2") return DIFF_DEADLINE;
  if (v === "repair_failing") return DIFF_ASSIGN;
  return [];
}

/* ------------------------------------------------------------------ public */

function defsOf(v: RevisionVariant): ScenarioDef[] {
  return v === "repair" ? repairDefs(false) : v === "repair_failing" ? repairDefs(true) : workshopDefs(v === "legacy" ? "initial" : v);
}

/** Test counts shown in the revision list. */
export function countsOf(v: RevisionVariant): TestCounts {
  const r = reportOf(defsOf(v));
  return { total: r.total, passed: r.passed, failed: r.failed };
}

/** The BotSpec of a stored mock revision. */
export function specOf(rev: StoredRevision): BotSpec {
  const repair = rev.variant === "repair" || rev.variant === "repair_failing";
  return repair
    ? repairSpec(rev.variant === "repair_failing")
    : workshopSpec({ capacity: capacityOf(rev.variant), deadlineHours: rev.variant === "deadline2" ? 2 : null });
}

/** RevisionDetail for a stored mock revision. */
export function detailOf(rev: StoredRevision): RevisionDetail {
  const defs = defsOf(rev.variant);
  const spec = specOf(rev);
  return {
    id: rev.id,
    bot_id: rev.bot_id,
    number: rev.number,
    status: rev.status,
    parent_id: rev.parent_id,
    change_request: rev.change_request,
    created_at: rev.created_at,
    activated_at: rev.activated_at,
    spec,
    requirements: requirementsOf(rev.variant),
    scenarios: hasNoStoredTests(rev) ? null : defs.map(scenarioOf),
    superseded: hasNoStoredTests(rev) ? null : [],
    test_report: hasNoStoredTests(rev) ? null : reportOf(defs),
    diff: diffOf(rev.variant),
  };
}

/** The variant a revision created by a mock agent run carries, from its parent's. */
export function nextVariant(parent: RevisionVariant | null): RevisionVariant {
  if (parent === null) return "initial";
  if (parent === "repair" || parent === "repair_failing") return "repair";
  if (parent === "legacy") return "initial";
  if (parent === "initial") return "cap12";
  return "deadline2";
}
