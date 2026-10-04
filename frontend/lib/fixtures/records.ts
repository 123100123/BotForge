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

  const bySepehr = records.filter((r) => r.collection !== "repair");
  const byTamir = records.filter((r) => r.collection === "repair");
  return { bot_sepehr: bySepehr, bot_tamir: byTamir };
}

export const LAST_FIXTURE_RECORD_ID = 100; // mock record ids created later start above this
