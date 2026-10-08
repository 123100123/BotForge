/** Example businesses for onboarding and for the first build: each prefills a realistic Persian description. */
export interface BusinessExample {
  id: string;
  /** Chip text. */
  label: string;
  /** A plausible business name, used when the name field is still empty. */
  name: string;
  description: string;
}

export const BUSINESS_EXAMPLES: BusinessExample[] = [
  {
    id: "training",
    label: "آموزشگاه و کارگاه‌ها",
    name: "آموزشگاه نوآوران",
    description:
      "من یک آموزشگاه دارم و کارگاه‌های آموزشی برگزار می‌کنم. می‌خواهم مشتری‌ها در ربات تلگرام لیست کارگاه‌ها را ببینند و ثبت‌نام کنند. ظرفیت هر کارگاه ۱۰ نفر است. اگر ظرفیت پر شد وارد لیست انتظار شوند و اگر کسی انصراف داد، نفر اول لیست انتظار خودکار جایگزین شود. امکان لغو ثبت‌نام هم باشد.",
  },
  {
    id: "cafe",
    label: "کافه و سفارش آنلاین",
    name: "کافه نیلوفر",
    description:
      "من یک کافه کوچک دارم. می‌خواهم مشتری‌ها در ربات تلگرام منوی نوشیدنی‌ها و کیک‌ها را با قیمت ببینند، چند مورد را سفارش بدهند و نام و ساعت تحویل را بنویسند. هر سفارش جدید برای من در تلگرام بیاید و بتوانم آن را تأیید یا تحویل‌شده کنم. فهرست محصولات را خودم بتوانم تغییر بدهم.",
  },
  {
    id: "repair",
    label: "تعمیرات لوازم خانگی",
    name: "تعمیرات خانگی پارس",
    description:
      "من تعمیرات لوازم خانگی دارم. می‌خواهم مشتری‌ها از ربات تلگرام درخواست تعمیر ثبت کنند و نوع دستگاه، مشکل و شمارهٔ تماس را بنویسند. هر درخواست برای من بیاید و من آن را تأیید یا رد کنم و مشتری از نتیجه باخبر شود.",
  },
];

/** Example sentences for changing a business that is already live. */
export const CHANGE_EXAMPLES: { label: string; text: string }[] = [
  { label: "ظرفیت را ۱۲ نفر کن", text: "ظرفیت هر کارگاه را ۱۲ نفر کن." },
  { label: "مهلت لغو ثبت‌نام", text: "لغو ثبت‌نام فقط تا ۲ ساعت قبل از شروع ممکن باشد." },
  { label: "گزینهٔ «تماس با ما»", text: "یک گزینهٔ «تماس با ما» به منوی ربات اضافه کن." },
];
