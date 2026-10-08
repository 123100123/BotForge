import type { BotSpec, FieldDef } from "@/lib/types";

function field(key: string, label: string, type: FieldDef["type"], required = true, extra: Partial<FieldDef> = {}): FieldDef {
  return { key, label, type, required, choices: null, default: null, ...extra };
}

/** A community-events bot: an events booking (RSVP with waitlist), support and approval requests. */
export function eventsSpec(): BotSpec {
  return {
    spec_version: 1,
    bot: {
      name: "مرکز رویدادهای نیلوفر",
      welcome_text: "سلام! از منو رویدادهای پیش رو را ببینید و ثبت‌نام کنید.",
      timezone: "Asia/Tehran",
      language: "fa",
    },
    resources: [
      {
        key: "event",
        label: "رویداد",
        label_plural: "رویدادها",
        title_field: "title",
        fields: [
          field("title", "عنوان", "text"),
          field("description", "توضیحات", "long_text", false),
          field("category", "دسته‌بندی", "choice", false, { choices: ["کارگاه", "سخنرانی", "شبکه‌سازی"] }),
          field("starts_at", "زمان شروع", "datetime"),
          field("location", "مکان", "text", false),
          field("capacity", "ظرفیت", "integer"),
        ],
      },
    ],
    capabilities: [
      {
        type: "booking",
        enabled: true,
        audience: "everyone",
        key: "book_event",
        title: "ثبت‌نام در رویداد",
        resource: "event",
        capacity: { mode: "per_item", value: null, field: "capacity" },
        start_field: "starts_at",
        detail_fields: ["description", "starts_at", "location"],
        form_fields: [],
        one_active_per_user_per_item: true,
        max_active_per_user: null,
        closes_hours_before_start: null,
        waitlist: { enabled: true, auto_promote: true },
        cancellation: { enabled: true, deadline_hours: null },
        notify_owner_on: ["booked", "cancelled"],
        notify_user_on: ["promoted"],
        texts: [],
        preset: "events",
        reminder_hours_before: 24,
        category_field: "category",
      },
      {
        type: "request",
        enabled: true,
        audience: "everyone",
        key: "support",
        title: "پشتیبانی",
        form_fields: [field("subject", "موضوع", "text"), field("message", "پیام", "long_text"), field("phone", "تلفن تماس", "phone", false)],
        item_resource: null,
        statuses: [
          { key: "new", label: "جدید" },
          { key: "answered", label: "پاسخ داده شد" },
          { key: "closed", label: "بسته شد" },
        ],
        initial_status: "new",
        owner_actions: [
          { key: "answer", label: "پاسخ داده شد", from_statuses: ["new"], to_status: "answered" },
          { key: "close", label: "بستن", from_statuses: ["new", "answered"], to_status: "closed" },
        ],
        notify_owner_on: ["submitted"],
        notify_user_on: ["status_changed"],
        texts: [],
      },
      {
        type: "request",
        enabled: true,
        audience: "staff",
        key: "approvals",
        title: "تأییدیه‌ها",
        form_fields: [field("kind", "نوع درخواست", "choice", true, { choices: ["مرخصی", "خرید", "رزرو سالن"] }), field("details", "توضیحات", "long_text")],
        item_resource: null,
        statuses: [
          { key: "pending", label: "در انتظار تأیید" },
          { key: "approved", label: "تأیید شد" },
          { key: "rejected", label: "رد شد" },
        ],
        initial_status: "pending",
        owner_actions: [
          { key: "approve", label: "تأیید", from_statuses: ["pending"], to_status: "approved" },
          { key: "reject", label: "رد", from_statuses: ["pending"], to_status: "rejected" },
        ],
        notify_owner_on: ["submitted"],
        notify_user_on: ["status_changed"],
        texts: [],
      },
    ],
    menu: [
      { key: "events", label: "رویدادها", capability: "book_event", view: "main" },
      { key: "my_events", label: "ثبت‌نام‌های من", capability: "book_event", view: "mine" },
      { key: "support", label: "پشتیبانی", capability: "support", view: "main" },
    ],
  };
}
