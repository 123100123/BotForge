/**
 * Mock of POST /bots/{id}/simulator/events. A small deterministic runtime that returns data shaped
 * exactly like RuntimeResponse (messages, outcomes, effects). Workshop bots: start -> menu -> list ->
 * item -> book -> confirmed / waitlisted, my bookings, cancel (with promotion). Request bots: a
 * four-question form and owner approve/reject buttons. State is in memory only.
 */
import { formatDateTime, formatNumber, toFaDigits } from "@/lib/format";
import { ApiError } from "@/lib/errors";
import type {
  BookingCapability,
  BotSpec,
  NoticeKind,
  OutMessage,
  Outcome,
  Persona,
  RequestCapability,
  RuntimeButton,
  RuntimeEffect,
  RuntimeResponse,
  SimulatorEventBody,
} from "@/lib/types";

const NAMES: Record<string, string> = { ali: "علی", sara: "سارا", reza: "رضا", staff: "همکار", owner: "مدیر" };
const HOUR = 3_600_000;

interface SandboxWorkshop {
  id: number;
  title: string;
  teacher: string;
  price: number;
  startsInHours: number;
  /** Seats already taken by other (unnamed) customers. */
  fillers: (cap: number) => number;
}

const WORKSHOPS: SandboxWorkshop[] = [
  { id: 1, title: "کارگاه عکاسی موبایل", teacher: "مریم احمدی", price: 1_500_000, startsInHours: 48, fillers: () => 0 },
  { id: 2, title: "کارگاه سفال‌گری مقدماتی", teacher: "علی رضایی", price: 2_200_000, startsInHours: 72, fillers: (cap) => cap - 1 },
  { id: 3, title: "کارگاه فوری ارائه‌نویسی", teacher: "نگار کریمی", price: 900_000, startsInHours: 1, fillers: () => 0 },
];

interface SandboxBooking {
  id: number;
  workshop: number;
  who: string;
  status: "confirmed" | "waitlisted" | "cancelled";
}
interface SandboxRequest {
  id: number;
  who: string;
  status: string;
  answers: string[];
}
interface Sandbox {
  now: number;
  nextId: number;
  bookings: SandboxBooking[];
  requests: SandboxRequest[];
  /** Request form progress per persona. */
  forms: Record<string, string[]>;
}

const sandboxes = new Map<string, Sandbox>();

function sandboxOf(botId: string): Sandbox {
  let s = sandboxes.get(botId);
  if (!s) {
    s = { now: Date.now(), nextId: 1, bookings: [], requests: [], forms: {} };
    sandboxes.set(botId, s);
  }
  return s;
}

/** Clears the sandbox and returns the number of sample records "loaded". */
export function resetSandbox(botId: string, spec: BotSpec): number {
  sandboxes.delete(botId);
  sandboxOf(botId);
  return spec.capabilities.some((c) => c.type === "booking") ? WORKSHOPS.length : 0;
}

/* ------------------------------------------------------------------ helpers */

const btn = (label: string, data: string): RuntimeButton => ({ label, data });
const money = (n: number) => `${formatNumber(n)} تومان`;
const who = (id: string) => NAMES[id] ?? id;

function msg(to: string, text: string, buttons: RuntimeButton[][] = [], edit = false, notice: NoticeKind | null = null): OutMessage {
  return { to_actor_id: to, text, buttons, edit, notice };
}

function menuButtons(spec: BotSpec): RuntimeButton[][] {
  return spec.menu.map((m) => [btn(m.label, `m:${m.key}`)]);
}

function respond(messages: OutMessage[], outcomes: Outcome[] = [], effects: RuntimeEffect[] = []): RuntimeResponse {
  return { messages, outcomes, effects };
}

function welcome(spec: BotSpec, to: string, edit: boolean): OutMessage {
  return msg(to, spec.bot.welcome_text, menuButtons(spec), edit);
}

/* ------------------------------------------------------------------ workshop (booking) */

function seatsLeft(sb: Sandbox, w: SandboxWorkshop, cap: number): number {
  const taken = sb.bookings.filter((b) => b.workshop === w.id && b.status === "confirmed").length;
  return cap - w.fillers(cap) - taken;
}

function workshopEvent(spec: BotSpec, cap: BookingCapability, sb: Sandbox, e: SimulatorEventBody): RuntimeResponse {
  const me = e.persona;
  const capacity = cap.capacity.value ?? 10;
  const find = (id: number) => WORKSHOPS.find((w) => w.id === id);
  const mine = () => sb.bookings.filter((b) => b.who === me && b.status !== "cancelled");

  if (e.kind === "start") return respond([welcome(spec, me, false)]);
  if (e.kind === "text") return respond([welcome(spec, me, false)]);

  const [action, arg] = (e.data ?? "").split(":");
  const home = () => respond([welcome(spec, me, true)]);

  if (action === "m") {
    const item = spec.menu.find((m) => m.key === arg);
    if (!item) return home();
    if (item.capability === "info") {
      const pages = spec.capabilities.find((c) => c.type === "info");
      const text = pages && pages.type === "info" ? pages.pages.map((p) => `${p.title}\n${p.body}`).join("\n\n") : "";
      return respond([msg(me, text, [[btn("بازگشت", "h")]], true)]);
    }
    if (item.view === "mine") {
      const list = mine();
      if (list.length === 0) return respond([msg(me, "شما هنوز در کارگاهی ثبت‌نام نکرده‌اید.", [[btn("بازگشت", "h")]], true)]);
      const lines = list.map((b) => `• ${find(b.workshop)?.title}: ${b.status === "confirmed" ? "تأیید شده" : "در لیست انتظار"}`);
      return respond([
        msg(me, `ثبت‌نام‌های شما:\n${lines.join("\n")}`, [...list.map((b) => [btn(`لغو «${find(b.workshop)?.title}»`, `x:${b.id}`)]), [btn("بازگشت", "h")]], true),
      ]);
    }
    return respond([
      msg(me, "کارگاه مورد نظر را انتخاب کنید:", [...WORKSHOPS.map((w) => [btn(w.title, `w:${w.id}`)]), [btn("بازگشت", "h")]], true),
    ]);
  }

  if (action === "h") return home();

  if (action === "w") {
    const w = find(Number(arg));
    if (!w) return home();
    const left = seatsLeft(sb, w, capacity);
    const starts = formatDateTime(sb.now + w.startsInHours * HOUR);
    const text = `${w.title}\n\nمدرس: ${w.teacher}\nزمان شروع: ${starts}\nهزینه: ${money(w.price)}\n\nظرفیت باقی‌مانده: ${left > 0 ? toFaDigits(left) : "تکمیل (لیست انتظار فعال است)"}`;
    const existing = mine().find((b) => b.workshop === w.id);
    return respond([
      msg(me, text, [[existing ? btn("لغو ثبت‌نام", `x:${existing.id}`) : btn("ثبت‌نام", `b:${w.id}`)], [btn("بازگشت", "m:workshops")]], true),
    ]);
  }

  if (action === "b") {
    const w = find(Number(arg));
    if (!w) return home();
    const back = [[btn("ثبت‌نام‌های من", "m:my_bookings")], [btn("منوی اصلی", "h")]];
    if (mine().some((b) => b.workshop === w.id)) {
      return respond(
        [msg(me, `شما قبلاً در «${w.title}» ثبت‌نام کرده‌اید.`, back, true)],
        [{ capability: cap.key, action: "book", result: "rejected", reason: "duplicate", record_id: null }],
      );
    }
    const confirmed = seatsLeft(sb, w, capacity) > 0;
    const booking: SandboxBooking = { id: sb.nextId++, workshop: w.id, who: me, status: confirmed ? "confirmed" : "waitlisted" };
    sb.bookings.push(booking);
    const notice: NoticeKind = confirmed ? "booked" : "waitlisted";
    const messages = [
      msg(me, confirmed ? `ثبت‌نام شما در «${w.title}» تأیید شد.` : `ظرفیت «${w.title}» تکمیل است؛ شما در لیست انتظار قرار گرفتید.`, back, true),
    ];
    const effects: RuntimeEffect[] = [{ kind: "record_created", collection: cap.key, record_id: booking.id, status: booking.status, to_actor_id: null }];
    if (me !== "owner") {
      messages.push(msg("owner", `${confirmed ? "ثبت‌نام جدید" : "ورود به لیست انتظار"}: ${who(me)} در «${w.title}»`, [], false, notice));
      effects.push({ kind: "notification", collection: null, record_id: null, status: null, to_actor_id: "owner" });
    }
    return respond(messages, [{ capability: cap.key, action: "book", result: confirmed ? "confirmed" : "waitlisted", reason: null, record_id: booking.id }], effects);
  }

  if (action === "x") {
    const booking = sb.bookings.find((b) => b.id === Number(arg) && b.who === me && b.status !== "cancelled");
    const back = [[btn("ثبت‌نام‌های من", "m:my_bookings")], [btn("منوی اصلی", "h")]];
    if (!booking) return respond([msg(me, "این ثبت‌نام پیدا نشد.", back, true)]);
    const w = find(booking.workshop)!;
    const deadline = cap.cancellation.deadline_hours;
    if (deadline !== null && w.startsInHours < deadline) {
      return respond(
        [msg(me, `لغو ثبت‌نام فقط تا ${toFaDigits(deadline)} ساعت قبل از شروع کارگاه ممکن است.`, back, true)],
        [{ capability: cap.key, action: "cancel", result: "rejected", reason: "cancel_deadline_passed", record_id: booking.id }],
      );
    }
    const wasConfirmed = booking.status === "confirmed";
    booking.status = "cancelled";
    const messages = [msg(me, `ثبت‌نام شما در «${w.title}» لغو شد.`, back, true)];
    const effects: RuntimeEffect[] = [{ kind: "record_updated", collection: cap.key, record_id: booking.id, status: "cancelled", to_actor_id: null }];
    if (me !== "owner") {
      messages.push(msg("owner", `لغو ثبت‌نام: ${who(me)} از «${w.title}»`, [], false, "cancelled"));
    }
    if (wasConfirmed && cap.waitlist.auto_promote) {
      const next = sb.bookings.find((b) => b.workshop === w.id && b.status === "waitlisted");
      if (next) {
        next.status = "confirmed";
        messages.push(msg(next.who, `خبر خوب! جای شما در «${w.title}» از لیست انتظار تأیید شد.`, [[btn("ثبت‌نام‌های من", "m:my_bookings")]], false, "promoted"));
        effects.push({ kind: "record_updated", collection: cap.key, record_id: next.id, status: "confirmed", to_actor_id: null });
      }
    }
    return respond(messages, [{ capability: cap.key, action: "cancel", result: "cancelled", reason: null, record_id: booking.id }], effects);
  }

  return home();
}

/* ------------------------------------------------------------------ request */

const QUESTIONS = ["نوع دستگاه را بنویسید (مثلاً یخچال یا لباسشویی):", "مشکل را شرح دهید:", "شماره تماس را بنویسید:", "نشانی را بنویسید:"];

function requestEvent(spec: BotSpec, cap: RequestCapability, sb: Sandbox, e: SimulatorEventBody): RuntimeResponse {
  const me = e.persona;
  const statusLabel = (k: string) => cap.statuses.find((s) => s.key === k)?.label ?? k;
  const ownerButtons = (r: SandboxRequest): RuntimeButton[][] =>
    cap.owner_actions.filter((a) => a.from_statuses.includes(r.status)).map((a) => [btn(a.label, `o:${r.id}:${a.key}`)]);

  if (e.kind === "start") {
    delete sb.forms[me];
    return respond([welcome(spec, me, false)]);
  }
  if (e.kind === "text") {
    const form = sb.forms[me];
    if (!form) return respond([welcome(spec, me, false)]);
    form.push(e.text ?? "");
    if (form.length < QUESTIONS.length) return respond([msg(me, QUESTIONS[form.length])]);
    delete sb.forms[me];
    const request: SandboxRequest = { id: sb.nextId++, who: me, status: cap.initial_status, answers: form };
    sb.requests.push(request);
    const label = toFaDigits(request.id);
    return respond(
      [
        msg(me, `درخواست شما با شمارهٔ ${label} ثبت شد. نتیجه را از همین‌جا به شما اطلاع می‌دهیم.`, [[btn("منوی اصلی", "h")]]),
        msg("owner", `درخواست جدید ${label} از ${who(me)}\nدستگاه: ${form[0]}\nمشکل: ${form[1]}`, ownerButtons(request), false, "submitted"),
      ],
      [{ capability: cap.key, action: "submit", result: "submitted", reason: null, record_id: request.id }],
      [
        { kind: "record_created", collection: cap.key, record_id: request.id, status: request.status, to_actor_id: null },
        { kind: "notification", collection: null, record_id: null, status: null, to_actor_id: "owner" },
      ],
    );
  }

  const [action, arg, key] = (e.data ?? "").split(":");
  if (action === "m") {
    const item = spec.menu.find((m) => m.key === arg);
    if (item?.view === "mine") {
      const list = sb.requests.filter((r) => r.who === me);
      const text = list.length === 0 ? "شما هنوز درخواستی ثبت نکرده‌اید." : list.map((r) => `• درخواست ${toFaDigits(r.id)} (${r.answers[0]}): ${statusLabel(r.status)}`).join("\n");
      return respond([msg(me, text, [[btn("بازگشت", "h")]], true)]);
    }
    if (item?.capability === cap.key) {
      sb.forms[me] = [];
      return respond([msg(me, QUESTIONS[0])]);
    }
    const info = spec.capabilities.find((c) => c.type === "info");
    return respond([msg(me, info && info.type === "info" ? info.pages.map((p) => `${p.title}\n${p.body}`).join("\n\n") : "", [[btn("بازگشت", "h")]], true)]);
  }
  if (action === "o") {
    const request = sb.requests.find((r) => r.id === Number(arg));
    const act = cap.owner_actions.find((a) => a.key === key);
    if ((me !== "owner" && me !== "staff") || !request || !act) {
      return respond([msg(me, "این کار برای شما مجاز نیست.", [], true)], [{ capability: cap.key, action: "owner_action", result: "rejected", reason: "not_allowed", record_id: null }]);
    }
    if (!act.from_statuses.includes(request.status)) {
      return respond([msg(me, `این اقدام برای وضعیت «${statusLabel(request.status)}» ممکن نیست.`, ownerButtons(request), true)], [
        { capability: cap.key, action: "owner_action", result: "rejected", reason: "not_allowed", record_id: request.id },
      ]);
    }
    request.status = act.to_status;
    return respond(
      [
        msg(me, `درخواست ${toFaDigits(request.id)} از ${who(request.who)}: ${statusLabel(request.status)}`, ownerButtons(request), true),
        msg(request.who, `وضعیت درخواست ${toFaDigits(request.id)} شما: ${statusLabel(request.status)}`, [], false, "status_changed"),
      ],
      [{ capability: cap.key, action: "owner_action", result: "ok", reason: null, record_id: request.id }],
      [{ kind: "record_updated", collection: cap.key, record_id: request.id, status: request.status, to_actor_id: null }],
    );
  }
  return respond([welcome(spec, me, true)]);
}

/* ------------------------------------------------------------------ entry */

export function simulate(botId: string, spec: BotSpec, body: SimulatorEventBody): RuntimeResponse {
  const personas: Persona[] = ["ali", "sara", "reza", "staff", "owner"];
  if (!personas.includes(body.persona)) throw new ApiError("invalid_persona", "کاربر آزمایشی نامعتبر است.", 422);
  const sb = sandboxOf(botId);
  const booking = spec.capabilities.find((c): c is BookingCapability => c.type === "booking");
  if (booking) return workshopEvent(spec, booking, sb, body);
  const request = spec.capabilities.find((c): c is RequestCapability => c.type === "request");
  if (request) return requestEvent(spec, request, sb, body);
  return respond([welcome(spec, body.persona, body.kind === "callback")]);
}

