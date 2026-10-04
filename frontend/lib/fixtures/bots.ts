import type { Bot } from "@/lib/types";
import type { StoredRevision } from "./revisions";

const DAY = 86_400_000;
const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();

/** Bots every fresh mock session starts with. Timestamps are relative to the first load. */
export function initialMockBots(): Bot[] {
  return [
    {
      id: "bot_novin",
      name: "آموزشگاه نوآوران",
      status: "draft",
      active_revision_id: null,
      active_revision_number: null,
      tg_username: null,
      owner_link_code: "novin-demo-code",
      owner_linked: false,
      created_at: iso(1 * DAY),
    },
    {
      id: "bot_sepehr",
      name: "کارگاه‌های سپهر",
      status: "live",
      active_revision_id: "rev_sepehr_3",
      active_revision_number: 3,
      tg_username: "sepehr_workshops_bot",
      owner_link_code: "sepehr-demo-code",
      owner_linked: true,
      created_at: iso(5 * DAY),
    },
    {
      id: "bot_tamir",
      name: "تعمیرات لوازم خانگی",
      status: "live",
      active_revision_id: "rev_tamir_1",
      active_revision_number: 1,
      tg_username: "tamirat_khaneh_bot",
      owner_link_code: "tamir-demo-code",
      owner_linked: false,
      created_at: iso(2 * DAY),
    },
  ];
}

/** Golden workshop bot: three revisions (initial, capacity 10 -> 12, cancellation deadline). The repair bot has a failing draft. */
export function initialMockRevisions(): StoredRevision[] {
  return [
    {
      id: "rev_sepehr_1",
      bot_id: "bot_sepehr",
      number: 1,
      parent_id: null,
      status: "superseded",
      change_request:
        "من یک آموزشگاه دارم و کارگاه‌های آموزشی برگزار می‌کنم. می‌خواهم مشتری‌ها در ربات تلگرام لیست کارگاه‌ها را ببینند و ثبت‌نام کنند. ظرفیت هر کارگاه ۱۰ نفر است. اگر ظرفیت پر شد وارد لیست انتظار شوند و اگر کسی انصراف داد، نفر اول لیست انتظار خودکار جایگزین شود. امکان لغو ثبت‌نام هم باشد.",
      created_at: iso(5 * DAY),
      activated_at: iso(5 * DAY),
      variant: "initial",
    },
    {
      id: "rev_sepehr_2",
      bot_id: "bot_sepehr",
      number: 2,
      parent_id: "rev_sepehr_1",
      status: "superseded",
      change_request: "ظرفیت هر کارگاه را ۱۲ نفر کن.",
      created_at: iso(3 * DAY),
      activated_at: iso(3 * DAY),
      variant: "cap12",
    },
    {
      id: "rev_sepehr_3",
      bot_id: "bot_sepehr",
      number: 3,
      parent_id: "rev_sepehr_2",
      status: "active",
      change_request: "لغو ثبت‌نام فقط تا ۲ ساعت قبل از شروع کارگاه ممکن باشد.",
      created_at: iso(1 * DAY),
      activated_at: iso(1 * DAY),
      variant: "deadline2",
    },
    {
      id: "rev_tamir_1",
      bot_id: "bot_tamir",
      number: 1,
      parent_id: null,
      status: "active",
      change_request:
        "من تعمیرات لوازم خانگی دارم. مشتری‌ها از ربات درخواست تعمیر ثبت کنند و من هر درخواست را تأیید یا رد کنم.",
      created_at: iso(2 * DAY),
      activated_at: iso(2 * DAY),
      variant: "repair",
    },
    {
      id: "rev_tamir_2",
      bot_id: "bot_tamir",
      number: 2,
      parent_id: "rev_tamir_1",
      status: "draft",
      change_request: "بعد از تأیید، بتوانم درخواست را به تکنسین ارجاع بدهم.",
      created_at: iso(2 * 3_600_000),
      activated_at: null,
      variant: "repair_failing",
    },
  ];
}
