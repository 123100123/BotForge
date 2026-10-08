import type { DataRecord } from "@/lib/types";

const H = 3_600_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

/** Live records of the mock bots. Ids are unique across a mock session. */
export function initialMockRecords(): Record<string, DataRecord[]> {
  let id = 0;
  const records: DataRecord[] = [];
  const add = (
    collection: string,
    data: Record<string, unknown>,
    extra: Partial<Pick<DataRecord, "status" | "actor_id" | "item_id">> = {},
    createdAgoH = 24,
  ) => {
    id += 1;
    records.push({
      id,
      collection,
      data,
      status: extra.status ?? null,
      actor_id: extra.actor_id ?? null,
      item_id: extra.item_id ?? null,
      created_at: iso(-createdAgoH * H),
      updated_at: iso(-createdAgoH * H),
    });
    return id;
  };

  const w1 = add("workshop", { title: "کارگاه عکاسی با موبایل", description: "آشنایی با اصول نوردهی و ترکیب‌بندی در عکاسی با موبایل.", teacher: "مریم احمدی", level: "مقدماتی", starts_at: iso(48 * H), price: 1_500_000, online: false }, {}, 120);
  const w2 = add("workshop", { title: "طراحی لوگو با ایلاستریتور", description: "از طرح اولیه تا خروجی نهایی یک لوگوی حرفه‌ای.", teacher: "امیر حسینی", level: "متوسط", starts_at: iso(96 * H), price: 2_400_000, online: true }, {}, 118);
  add("workshop", { title: "مبانی بازاریابی دیجیتال", description: "معرفی کانال‌ها و تحلیل نتایج برای کسب‌وکارهای کوچک.", teacher: "نگار کریمی", level: "مقدماتی", starts_at: iso(168 * H), price: 1_800_000, online: true }, {}, 100);
  const w4 = add("workshop", { title: "سفال‌گری مقدماتی", description: "ساخت ظروف ساده با چرخ سفال‌گری.", teacher: "علی رضایی", level: "مقدماتی", starts_at: iso(240 * H), price: 2_200_000, online: false }, {}, 90);

  // Bookings: 12 confirmed + 2 waitlisted on workshop 1, a few on others.
  for (let i = 1; i <= 12; i += 1) {
    add("book_workshop", {}, { status: "confirmed", actor_id: `50123456${String(i).padStart(2, "0")}`, item_id: w1 }, 80 - i * 3);
  }
  add("book_workshop", {}, { status: "waitlisted", actor_id: "5012345701", item_id: w1 }, 20);
  add("book_workshop", {}, { status: "waitlisted", actor_id: "5012345702", item_id: w1 }, 10);
  add("book_workshop", {}, { status: "confirmed", actor_id: "5012345801", item_id: w2 }, 30);
  add("book_workshop", {}, { status: "confirmed", actor_id: "5012345802", item_id: w2 }, 28);
  add("book_workshop", {}, { status: "cancelled", actor_id: "5012345803", item_id: w2 }, 26);
  add("book_workshop", {}, { status: "confirmed", actor_id: "5012345901", item_id: w4 }, 5);

  const req = (device: string, problem: string, phone: string, address: string, status: string, actor: string, ago: number) =>
    add("repair", { device, problem, phone, address }, { status, actor_id: actor }, ago);
  req("یخچال", "یخچال خنک نمی‌کند و صدای غیرعادی می‌دهد.", "09121234567", "تهران، خیابان ولیعصر، کوچهٔ دوم، پلاک ۸", "new", "6001001", 2);
  req("لباسشویی", "آب را تخلیه نمی‌کند.", "09131234567", "اصفهان، خیابان چهارباغ، پلاک ۲۱", "new", "6001002", 5);
  req("ماشین ظرفشویی", "برق دستگاه وصل نمی‌شود.", "09351234567", "تهران، سعادت‌آباد، پلاک ۴", "approved", "6001003", 20);
  req("اجاق گاز", "یکی از شعله‌ها روشن نمی‌شود.", "09101234567", "کرج، گوهردشت، بلوک ۳", "done", "6001004", 70);

  // bot_niloofar: events with registrations (confirmed / waitlisted / cancelled), support and approval requests.
  const e1 = add("event", { title: "کارگاه عکاسی خیابانی", description: "پیاده‌روی عکاسی در محلهٔ قدیمی با مربی.\nدوربین یا موبایل همراه داشته باشید.", category: "کارگاه", starts_at: iso(30 * H), location: "تهران، خیابان ولیعصر، خانهٔ هنرمندان", capacity: 12 }, {}, 200);
  const e2 = add("event", { title: "سخنرانی: آیندهٔ کسب‌وکارهای کوچک", description: "گفت‌وگو دربارهٔ ابزارهای دیجیتال برای فروشگاه‌های محلی.", category: "سخنرانی", starts_at: iso(100 * H), location: "تالار همایش‌های نیلوفر", capacity: 40 }, {}, 190);
  const e3 = add("event", { title: "شبکه‌سازی صاحبان کسب‌وکار", description: "دورهمی آزاد برای آشنایی و تبادل تجربه.", category: "شبکه‌سازی", starts_at: iso(200 * H), location: "کافه‌ای در سعادت‌آباد", capacity: 25 }, {}, 180);
  const e4 = add("event", { title: "کارگاه نوشتن محتوا برای شبکه‌های اجتماعی", description: "برگزار شد.", category: "کارگاه", starts_at: iso(-120 * H), location: "تهران، میدان انقلاب", capacity: 15 }, {}, 400);
  const nb = (item: number, status: string, n: number, ago: number) => add("book_event", {}, { status, actor_id: `70123${String(item).padStart(2, "0")}${String(n).padStart(3, "0")}`, item_id: item }, ago);
  for (let i = 1; i <= 12; i += 1) nb(e1, "confirmed", i, 150 - i * 4);
  nb(e1, "waitlisted", 13, 40);
  nb(e1, "waitlisted", 14, 30);
  nb(e1, "cancelled", 15, 90);
  for (let i = 1; i <= 17; i += 1) nb(e2, "confirmed", i, 140 - i * 3);
  nb(e2, "cancelled", 18, 60);
  for (let i = 1; i <= 6; i += 1) nb(e3, "confirmed", i, 100 - i * 5);
  for (let i = 1; i <= 15; i += 1) nb(e4, "confirmed", i, 300 - i * 6);

  const sup = (subject: string, message: string, status: string, actor: string, ago: number) =>
    add("support", { subject, message, phone: "09121230000" }, { status, actor_id: actor }, ago);
  sup("لغو ثبت‌نام بعد از مهلت", "ثبت‌نامم را فراموش کردم لغو کنم، می‌شود هنوز انجام شود؟", "new", "70123010001", 3);
  sup("گواهی حضور", "برای کارگاه قبلی گواهی حضور می‌خواهم.", "answered", "70123010002", 30);
  sup("تغییر مکان رویداد", "مکان سخنرانی هنوز همان تالار است؟", "closed", "70123010003", 80);
  const apr = (kind: string, details: string, status: string, actor: string, ago: number) => add("approvals", { kind, details }, { status, actor_id: actor }, ago);
  apr("رزرو سالن", "سالن کوچک برای جلسهٔ تیم، پنجشنبه ساعت ۱۰.", "pending", "70123020001", 4);
  apr("خرید", "خرید ۲۰ صندلی تاشو برای کارگاه‌ها.", "pending", "70123020002", 12);
  apr("مرخصی", "یک روز مرخصی هفتهٔ آینده.", "approved", "70123020003", 70);
  apr("خرید", "پروژکتور جدید.", "rejected", "70123020004", 120);

  const niloofarKeys = new Set(["event", "book_event", "support", "approvals"]);
  const byNiloofar = records.filter((r) => niloofarKeys.has(r.collection));
  const bySepehr = records.filter((r) => r.collection !== "repair" && !niloofarKeys.has(r.collection));
  const byTamir = records.filter((r) => r.collection === "repair");
  return { bot_sepehr: bySepehr, bot_tamir: byTamir, bot_niloofar: byNiloofar };
}

const NILOOFAR_NAMES = [
  "نگین کاظمی", "پویا صادقی", "مهسا رحیمی", "امیرحسین نادری", "زهرا موسوی", "علی رضایی", "سارا احمدی", "محمد کریمی", "ندا حسینی",
  "رضا قاسمی", "مریم جعفری", "کاوه فرهادی", "الهام صالحی", "بهرام یزدانی", "شیرین عباسی", "داریوش پاکزاد", "نسترن توکلی", "حامد رستمی",
];

/** Display name for the fixture actors of bot_niloofar (their ids start with 70123); null for any other id. */
export function niloofarActorName(actorId: string): string | null {
  if (!actorId.startsWith("70123")) return null;
  let h = 0;
  for (const ch of actorId) h = (h * 31 + ch.charCodeAt(0)) % 9973;
  return NILOOFAR_NAMES[h % NILOOFAR_NAMES.length];
}

export const LAST_FIXTURE_RECORD_ID = 100; // mock record ids created later start above this
