import type { AttentionListItem } from "@/components/app/attention-list";
import type { MetricStripItem } from "@/components/app/metric-strip";
import type { ChatMessage } from "@/components/simulator/chat-message-list";
import type { Question, Requirements, SeriesPoint, SpecChange } from "@/lib/types";

/**
 * Static fixture data for the landing page (a training center, «کارگاه‌های سپهر»). The product components on the
 * page are the real ones; only their input lives here, so it never depends on a session or the clock.
 */

export const BUSINESS_NAME = "کارگاه‌های سپهر";
export const CTA_SIGNUP_LABEL = "کسب‌وکارتان را توضیح دهید";

/* ------------------------------------------------------------------ Hero */

export const HERO_ATTENTION: AttentionListItem[] = [
  { id: "orders", tone: "warning", text: "۳ سفارش جدید منتظر تأیید است.", href: "/login", actionLabel: "بررسی" },
  {
    id: "event",
    tone: "info",
    text: "کارگاه طراحی لوگو فردا ساعت ۱۷ است و ۱۸ از ۲۰ نفر ثبت‌نام کرده‌اند.",
    href: "/login",
    actionLabel: "ثبت‌نام‌ها",
  },
  { id: "file", tone: "danger", text: "ساختار فایل «sales-new-format» تغییر کرده است.", href: "/login", actionLabel: "رفع" },
];

export const HERO_METRICS: MetricStripItem[] = [
  { id: "signups_today", label: "ثبت‌نام امروز", value: 7 },
  { id: "orders", label: "سفارش‌ها", value: 13, previous: 15 },
  { id: "revenue", label: "درآمد", value: 9.1, unit: "میلیون تومان", previous: 8.4 },
  { id: "new_customers", label: "مشتری جدید", value: 23, previous: 19 },
];

export const HERO_CHAT: ChatMessage[] = [
  {
    from: "bot",
    text: "سلام! کارگاه‌های باز این هفته:",
    buttons: [["طراحی لوگو", "عکاسی موبایل"]],
  },
  { from: "user", text: "طراحی لوگو" },
  { from: "bot", text: "ثبت شد. ۱۹ از ۲۰ نفر.", buttons: [["لغو ثبت‌نام", "منوی اصلی"]] },
];

export const HERO_SUMMARY =
  "نمونه‌ای از مرکز کنترل کسب‌وکار با سه مورد نیازمند توجه و چهار شاخص، و گفتگوی یک مشتری که در کارگاه ثبت‌نام می‌کند.";

/* ------------------------------------------------------------------ Roles */

export type RoleId = "customer" | "staff" | "manager";

export interface RoleDemo {
  id: RoleId;
  label: string;
  sentence: string;
  subtitle: string;
  points: string[];
  messages: ChatMessage[];
}

export const ROLES: RoleDemo[] = [
  {
    id: "customer",
    label: "مشتری",
    sentence: "مشتری از همان گفتگوی تلگرام سفارش می‌دهد یا در رویداد ثبت‌نام می‌کند و وضعیتش را می‌بیند.",
    subtitle: "نمای مشتری",
    points: ["فهرست کارگاه‌ها و محصولات", "ثبت‌نام، لغو و لیست انتظار", "سفارش و پیگیری وضعیت آن"],
    messages: [
      {
        from: "bot",
        text: "یادآوری: کارگاه طراحی لوگو فردا ساعت ۱۷ برگزار می‌شود. می‌آیید؟",
        buttons: [["می‌آیم", "نمی‌آیم"]],
      },
      { from: "user", text: "می‌آیم" },
      { from: "bot", text: "ثبت شد. ۱۹ نفر از ۲۰ نفر ظرفیت پر شده است.", buttons: [["سفارش‌های من", "منوی اصلی"]] },
    ],
  },
  {
    id: "staff",
    label: "کارمند",
    sentence: "کارمند صف کارهای امروز را می‌بیند و گزارش روزانهٔ اکسل را همان‌جا می‌فرستد.",
    subtitle: "نمای کارمند",
    points: ["صف کارهای امروز", "ارسال گزارش روزانه با فایل اکسل", "ثبت وضعیت کار از تلگرام"],
    messages: [
      { from: "bot", text: "صف امروز: ۴ سفارش منتظر آماده‌سازی.", buttons: [["نمایش صف", "ارسال گزارش اکسل"]] },
      { from: "user", text: "فایل فروش امروز: sales-today.xlsx" },
      { from: "bot", text: "فایل تحلیل شد. ۱ مورد غیرعادی پیدا شد و برای مدیر فرستاده شد." },
    ],
  },
  {
    id: "manager",
    label: "مدیر",
    sentence: "مدیر خلاصهٔ روز را دریافت می‌کند و درخواست‌ها را با یک دکمه تأیید می‌کند.",
    subtitle: "نمای مدیر",
    points: ["خلاصهٔ روزانه در تلگرام", "تأیید یا رد درخواست‌ها", "پرسش از دستیار دربارهٔ داده‌ها"],
    messages: [
      { from: "bot", text: "خلاصهٔ امروز: ۷ ثبت‌نام، ۳ سفارش جدید و ۱ درخواست منتظر تأیید." },
      { from: "bot", text: "نگار احمدی درخواست دو روز مرخصی کرده است.", buttons: [["تأیید", "رد"]] },
      { from: "user", text: "تأیید" },
      { from: "bot", text: "تأیید شد و به نگار اطلاع داده شد." },
    ],
  },
];

/* ------------------------------------------------------------------ How it is built */

export const HOW_DESCRIPTION =
  "من یک آموزشگاه دارم و کارگاه برگزار می‌کنم. می‌خواهم مشتری‌ها در ربات تلگرام کارگاه‌ها را ببینند و ثبت‌نام کنند. ظرفیت هر کارگاه ۱۰ نفر است و اگر پر شد وارد لیست انتظار شوند.";

export const HOW_REQUIREMENTS: Requirements = {
  business_summary: "آموزشگاهی که کارگاه برگزار می‌کند و ثبت‌نام‌ها را از تلگرام می‌گیرد.",
  items: [
    { id: "R1", kind: "capability", statement: "مشتری‌ها فهرست کارگاه‌ها را در ربات می‌بینند.", status: "confirmed" },
    { id: "R2", kind: "capability", statement: "مشتری‌ها در یک کارگاه ثبت‌نام می‌کنند.", status: "confirmed" },
    { id: "R3", kind: "rule", statement: "ظرفیت هر کارگاه ۱۰ نفر است.", status: "confirmed" },
    { id: "R4", kind: "rule", statement: "اگر ظرفیت پر شد، ثبت‌نام‌کننده وارد لیست انتظار می‌شود.", status: "confirmed" },
    { id: "R5", kind: "rule", statement: "هر نفر در هر کارگاه فقط یک ثبت‌نام فعال دارد.", status: "assumed" },
    { id: "R6", kind: "notification", statement: "با هر ثبت‌نام یا لغو، مدیر در تلگرام باخبر می‌شود.", status: "assumed" },
  ],
  unsupported: [],
  open_questions: [],
};

export const HOW_QUESTIONS: Question[] = [
  {
    id: "Q1",
    text: "ثبت‌نام را تا چند ساعت قبل از شروع کارگاه می‌شود لغو کرد؟",
    why: "برای تعیین مهلت لغو لازم است.",
    severity: "blocking",
    options: ["تا ۲ ساعت قبل", "تا ۲۴ ساعت قبل", "هر زمان"],
  },
];

export const HOW_TESTS = {
  total: 21,
  passed: 21,
  failed: 0,
  note: "۱۸ آزمون از روی پیکربندی و ۳ آزمون از روی خواستهٔ شما ساخته شد.",
};

export const HOW_CHANGE_REQUEST = "ظرفیت هر کارگاه را ۱۲ نفر کن.";

export const HOW_DIFF: SpecChange[] = [
  {
    path: ["capabilities", "book_workshop", "capacity", "value"],
    kind: "changed",
    old: 10,
    new: 12,
    label_fa: "ظرفیت هر کارگاه: ۱۰ نفر ← ۱۲ نفر",
  },
];

/* ------------------------------------------------------------------ Capability index */

export interface CapabilityEntry {
  name: string;
  purpose: string;
  soon?: boolean;
}

export interface CapabilityGroup {
  id: string;
  title: string;
  items: CapabilityEntry[];
}

/** The 18 registry capabilities in their 5 categories (names as in backend/app/capabilities/registry.py). */
export const CAPABILITY_GROUPS: CapabilityGroup[] = [
  {
    id: "commerce",
    title: "تجارت",
    items: [
      { name: "فهرست محصولات و خدمات", purpose: "نمایش قیمت و جزئیات در ربات" },
      { name: "فروشگاه و سفارش‌ها", purpose: "سبد خرید، ثبت و پیگیری سفارش" },
      { name: "موجودی انبار", purpose: "شمارش موجودی و هشدار کمبود" },
      { name: "پرداخت آنلاین", purpose: "دریافت پول داخل تلگرام", soon: true },
    ],
  },
  {
    id: "operations",
    title: "عملیات",
    items: [
      { name: "رزرو و نوبت‌دهی", purpose: "ظرفیت، لیست انتظار و لغو" },
      { name: "فرم‌ها و درخواست‌ها", purpose: "ثبت و پیگیری درخواست مشتری" },
      { name: "تأیید و گردش کار", purpose: "صف تأیید برای مدیر" },
    ],
  },
  {
    id: "team",
    title: "تیم",
    items: [
      { name: "رویدادها", purpose: "ثبت‌نام، ظرفیت و یادآوری خودکار" },
      { name: "اطلاعیه‌ها", purpose: "پیام همگانی به کاربران و گروه‌ها" },
      { name: "نقش‌ها و کارکنان", purpose: "دعوت با لینک، نقش کارمند یا مدیر" },
      { name: "گزارش روزانهٔ کارکنان", purpose: "گزارش کار مستقیم از تلگرام" },
    ],
  },
  {
    id: "intelligence",
    title: "هوش کسب‌وکار",
    items: [
      { name: "گزارش‌ها و داشبورد", purpose: "شاخص و نمودار فروش و فعالیت" },
      { name: "تحلیل فایل اکسل", purpose: "آمار و موارد غیرعادی فایل" },
      { name: "گزارش‌های زمان‌بندی‌شده", purpose: "خلاصهٔ روزانه و هفتگی در تلگرام" },
      { name: "دستیار مدیر", purpose: "پرسش دربارهٔ داده‌های کسب‌وکار" },
    ],
  },
  {
    id: "customer",
    title: "مشتریان",
    items: [
      { name: "اطلاعات و معرفی", purpose: "نشانی، ساعت کاری و پرسش‌های متداول" },
      { name: "پشتیبانی", purpose: "دریافت و پاسخ به پیام مشتری" },
      { name: "نظرسنجی و بازخورد", purpose: "امتیاز و نظر مشتریان" },
    ],
  },
];

/* ------------------------------------------------------------------ Reports */

export const REPORT_METRICS: MetricStripItem[] = [
  { id: "revenue", label: "درآمد هفته", value: 9.1, unit: "میلیون تومان", previous: 8.4 },
  { id: "signups", label: "ثبت‌نام‌ها", value: 31, previous: 40 },
  { id: "occupancy", label: "ظرفیت پرشده", value: 89, unit: "درصد", previous: 82 },
  { id: "new_customers", label: "مشتری جدید", value: 23, previous: 19 },
];

export const REPORT_SERIES: SeriesPoint[] = [
  { label: "شنبه", value: 3 },
  { label: "یکشنبه", value: 5 },
  { label: "دوشنبه", value: 4 },
  { label: "سه‌شنبه", value: 6 },
  { label: "چهارشنبه", value: 5 },
  { label: "پنجشنبه", value: 8 },
  { label: "جمعه", value: 7 },
];

export interface SheetRow {
  product: string;
  amount: string;
  note?: string;
  anomaly?: boolean;
}

export const SHEET_FILE = "sales-today.xlsx";
export const SHEET_ROWS: SheetRow[] = [
  { product: "قهوه", amount: "۹۵۰٬۰۰۰", note: "سه برابر معمول", anomaly: true },
  { product: "چای", amount: "۳۱۰٬۰۰۰" },
  { product: "شیرینی", amount: "۱۸۰٬۰۰۰" },
];
