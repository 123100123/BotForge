import type { BotSpec, FieldDef } from "@/lib/types";

function field(
  key: string,
  label: string,
  type: FieldDef["type"],
  required = true,
  extra: Partial<FieldDef> = {},
): FieldDef {
  return { key, label, type, required, choices: null, default: null, ...extra };
}

export interface WorkshopSpecOptions {
  capacity: number;
  deadlineHours: number | null;
  /** Adds a per-user limit (used by the failing draft fixture). */
  maxActivePerUser?: number | null;
}

/** examples/workshop.botspec.json with the knobs the demo modifications change. */
export function workshopSpec(opts: WorkshopSpecOptions): BotSpec {
  return {
    spec_version: 1,
    bot: {
      name: "کارگاه‌های سپهر",
      welcome_text: "سلام! به ربات کارگاه‌های آموزشگاه خوش آمدید. از منوی زیر می‌توانید کارگاه‌ها را ببینید و ثبت‌نام کنید.",
      timezone: "Asia/Tehran",
      language: "fa",
    },
    resources: [
      {
        key: "workshop",
        label: "کارگاه",
        label_plural: "کارگاه‌ها",
        title_field: "title",
        fields: [
          field("title", "عنوان", "text"),
          field("description", "توضیحات", "long_text"),
          field("teacher", "مدرس", "text"),
          field("level", "سطح", "choice", false, { choices: ["مقدماتی", "متوسط", "پیشرفته"] }),
          field("starts_at", "زمان شروع", "datetime"),
          field("price", "هزینه (تومان)", "integer", false),
          field("online", "برگزاری آنلاین", "boolean", false, { default: "false" }),
        ],
      },
    ],
    capabilities: [
      {
        type: "info",
        key: "info",
        title: "دربارهٔ ما",
        pages: [
          { key: "about", title: "دربارهٔ آموزشگاه", body: "آموزشگاه ما کارگاه‌های آموزشی کوتاه‌مدت و کاربردی برگزار می‌کند." },
          { key: "address", title: "نشانی و تماس", body: "تهران، خیابان انقلاب، پلاک ۱۲. تلفن: ۰۲۱-۱۲۳۴۵۶۷۸" },
        ],
      },
      {
        type: "booking",
        key: "book_workshop",
        title: "ثبت‌نام در کارگاه",
        resource: "workshop",
        capacity: { mode: "fixed", value: opts.capacity, field: null },
        start_field: "starts_at",
        detail_fields: ["description", "teacher", "starts_at", "price"],
        form_fields: [],
        one_active_per_user_per_item: true,
        max_active_per_user: opts.maxActivePerUser ?? null,
        closes_hours_before_start: null,
        waitlist: { enabled: true, auto_promote: true },
        cancellation: { enabled: true, deadline_hours: opts.deadlineHours },
        notify_owner_on: ["booked", "cancelled"],
        notify_user_on: ["promoted"],
        texts: [],
      },
    ],
    menu: [
      { key: "workshops", label: "کارگاه‌ها و ثبت‌نام", capability: "book_workshop", view: "main" },
      { key: "my_bookings", label: "ثبت‌نام‌های من", capability: "book_workshop", view: "mine" },
      { key: "about", label: "دربارهٔ ما", capability: "info", view: "main" },
    ],
  };
}

/** examples/repair.botspec.json; `withAssign` adds the owner action of the failing draft. */
export function repairSpec(withAssign: boolean): BotSpec {
  const statuses = [
    { key: "new", label: "در انتظار بررسی" },
    { key: "approved", label: "تأیید شده" },
    { key: "rejected", label: "رد شده" },
    { key: "done", label: "انجام شده" },
    ...(withAssign ? [{ key: "assigned", label: "ارجاع به تکنسین" }] : []),
  ];
  return {
    spec_version: 1,
    bot: {
      name: "تعمیرات لوازم خانگی",
      welcome_text: "سلام! از منوی زیر درخواست تعمیر ثبت کنید یا وضعیت درخواست‌های خود را ببینید.",
      timezone: "Asia/Tehran",
      language: "fa",
    },
    resources: [],
    capabilities: [
      {
        type: "request",
        key: "repair",
        title: "درخواست تعمیر",
        form_fields: [
          field("device", "نوع دستگاه", "text"),
          field("problem", "شرح مشکل", "long_text"),
          field("phone", "شماره تماس", "phone"),
          field("address", "نشانی", "long_text"),
        ],
        item_resource: null,
        statuses,
        initial_status: "new",
        owner_actions: [
          { key: "approve", label: "تأیید", from_statuses: ["new"], to_status: "approved" },
          { key: "reject", label: "رد", from_statuses: ["new"], to_status: "rejected" },
          {
            key: "mark_done",
            label: "انجام شد",
            from_statuses: withAssign ? ["approved", "assigned"] : ["approved"],
            to_status: "done",
          },
          ...(withAssign
            ? [{ key: "assign", label: "ارجاع به تکنسین", from_statuses: ["approved"], to_status: "assigned" }]
            : []),
        ],
        notify_owner_on: ["submitted"],
        notify_user_on: ["status_changed"],
        texts: [],
      },
      {
        type: "info",
        key: "info",
        title: "دربارهٔ ما",
        pages: [{ key: "hours", title: "ساعات کاری", body: "شنبه تا پنجشنبه، ساعت ۸ تا ۲۰" }],
      },
    ],
    menu: [
      { key: "new_request", label: "ثبت درخواست تعمیر", capability: "repair", view: "main" },
      { key: "my_requests", label: "درخواست‌های من", capability: "repair", view: "mine" },
      { key: "about", label: "دربارهٔ ما", capability: "info", view: "main" },
    ],
  };
}
