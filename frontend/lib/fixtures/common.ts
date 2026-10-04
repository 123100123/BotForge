import type { Requirements, SpecOutline } from "@/lib/types";

/** The golden create prompt, verbatim from examples/prompts.fa.md. */
export const GOLDEN_CREATE_PROMPT =
  "من یک آموزشگاه دارم و کارگاه‌های آموزشی برگزار می‌کنم. می‌خواهم مشتری‌ها در ربات تلگرام لیست کارگاه‌ها را ببینند و ثبت‌نام کنند. ظرفیت هر کارگاه ۱۰ نفر است. اگر ظرفیت پر شد وارد لیست انتظار شوند و اگر کسی انصراف داد، نفر اول لیست انتظار خودکار جایگزین شود. امکان لغو ثبت‌نام هم باشد.";

/** First golden modification, verbatim from examples/prompts.fa.md. */
export const GOLDEN_MODIFY_PROMPT = "ظرفیت هر کارگاه را ۱۲ نفر کن.";

const BUSINESS_SUMMARY =
  "آموزشگاهی که کارگاه‌های آموزشی برگزار می‌کند و می‌خواهد مشتریان از طریق ربات تلگرام کارگاه‌ها را ببینند، ثبت‌نام کنند و در صورت نیاز ثبت‌نام خود را لغو کنند.";

/** Requirements for the workshop bot. `capacityStatement` differs between the stages of the demo. */
export function workshopRequirements(capacityStatement: string): Requirements {
  return {
    business_summary: BUSINESS_SUMMARY,
    items: [
      { id: "R1", kind: "capability", statement: "مشتری‌ها می‌توانند فهرست کارگاه‌ها را در ربات ببینند.", status: "confirmed" },
      { id: "R2", kind: "capability", statement: "مشتری‌ها می‌توانند در یک کارگاه ثبت‌نام کنند.", status: "confirmed" },
      { id: "R3", kind: "rule", statement: capacityStatement, status: "confirmed" },
      { id: "R4", kind: "rule", statement: "اگر ظرفیت کارگاه پر شد، ثبت‌نام‌کننده وارد لیست انتظار می‌شود.", status: "confirmed" },
      { id: "R5", kind: "rule", statement: "با انصراف یک نفر، نفر اول لیست انتظار به‌طور خودکار جایگزین او می‌شود.", status: "confirmed" },
      { id: "R6", kind: "rule", statement: "مشتری‌ها می‌توانند ثبت‌نام خود را لغو کنند.", status: "confirmed" },
      { id: "R7", kind: "capability", statement: "مشتری‌ها می‌توانند ثبت‌نام‌های خود را ببینند.", status: "assumed" },
      { id: "R8", kind: "data", statement: "هر کارگاه عنوان، توضیحات، مدرس، زمان شروع و هزینه دارد.", status: "assumed" },
      { id: "R9", kind: "notification", statement: "با ثبت‌نام یا لغو ثبت‌نام، مدیر آموزشگاه در تلگرام مطلع می‌شود.", status: "assumed" },
      { id: "R10", kind: "rule", statement: "هر نفر در هر کارگاه فقط یک ثبت‌نام فعال می‌تواند داشته باشد.", status: "assumed" },
    ],
    unsupported: [],
    open_questions: [],
  };
}

/** Outline of examples/workshop.botspec.json. */
export const WORKSHOP_OUTLINE: SpecOutline = {
  bot_name: "کارگاه‌های آموزشگاه",
  resources: [
    {
      key: "workshop",
      label: "کارگاه",
      label_plural: "کارگاه‌ها",
      title_field: "title",
      fields: [
        { key: "title", label: "عنوان", type: "text", required: true, choices: null },
        { key: "description", label: "توضیحات", type: "long_text", required: true, choices: null },
        { key: "teacher", label: "مدرس", type: "text", required: true, choices: null },
        { key: "starts_at", label: "زمان شروع", type: "datetime", required: true, choices: null },
        { key: "price", label: "هزینه (تومان)", type: "integer", required: false, choices: null },
      ],
    },
  ],
  capabilities: [
    {
      key: "info",
      type: "info",
      title: "دربارهٔ ما",
      resource: null,
      form_fields: [],
      pages: [
        { key: "about", label: "دربارهٔ آموزشگاه" },
        { key: "address", label: "نشانی و تماس" },
      ],
      statuses: [],
      owner_actions: [],
    },
    {
      key: "book_workshop",
      type: "booking",
      title: "ثبت‌نام در کارگاه",
      resource: "workshop",
      form_fields: [],
      pages: [],
      statuses: [],
      owner_actions: [],
    },
  ],
  menu: [
    { key: "workshops", label: "کارگاه‌ها و ثبت‌نام", capability: "book_workshop", view: "main" },
    { key: "my_bookings", label: "ثبت‌نام‌های من", capability: "book_workshop", view: "mine" },
    { key: "about", label: "دربارهٔ ما", capability: "info", view: "main" },
  ],
};

/** Titles of the acceptance scenarios the create run writes. */
export const ACCEPTANCE_TITLES = {
  basic: "علی کارگاه را می‌بیند، ثبت‌نام می‌کند و مدیر مطلع می‌شود",
  promotion: "با انصراف یک نفر، نفر اول لیست انتظار جایگزین می‌شود",
  capacity: "ظرفیت ۱۰ نفر پر می‌شود و نفر یازدهم در لیست انتظار قرار می‌گیرد",
} as const;
