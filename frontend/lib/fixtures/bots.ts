import type { Bot, RevisionSummary } from "@/lib/types";

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
      created_at: iso(1 * DAY),
    },
    {
      id: "bot_sepehr",
      name: "کارگاه‌های سپهر",
      status: "live",
      active_revision_id: "rev_sepehr_1",
      active_revision_number: 1,
      tg_username: "sepehr_workshops_bot",
      created_at: iso(5 * DAY),
    },
  ];
}

export function initialMockRevisions(): RevisionSummary[] {
  return [
    {
      id: "rev_sepehr_1",
      bot_id: "bot_sepehr",
      number: 1,
      parent_id: null,
      status: "active",
      change_request:
        "من یک آموزشگاه دارم و کارگاه‌های آموزشی برگزار می‌کنم. می‌خواهم مشتری‌ها در ربات تلگرام لیست کارگاه‌ها را ببینند و ثبت‌نام کنند.",
      created_at: iso(5 * DAY),
      activated_at: iso(5 * DAY),
      tests_total: 12,
      tests_passed: 12,
    },
  ];
}
