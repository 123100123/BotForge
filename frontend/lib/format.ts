/** Persian number/date helpers. All user-visible numbers and dates go through here. */

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const TIME_ZONE = "Asia/Tehran";

/** Replace ASCII digits in a string with Persian digits. */
export function toFaDigits(value: string | number): string {
  return String(value).replace(/\d/g, (d) => FA_DIGITS[Number(d)]);
}

/** Persian-digit number with grouping, e.g. 1500000 -> ۱٬۵۰۰٬۰۰۰. */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat("fa-IR").format(value);
}

/** Plain count without grouping (ids, small counts). */
export function fa(value: number | string): string {
  return toFaDigits(value);
}

function parse(input: string | number | Date): Date | null {
  const d = input instanceof Date ? input : new Date(input);
  return Number.isNaN(d.getTime()) ? null : d;
}

const dateFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "long",
  day: "numeric",
  timeZone: TIME_ZONE,
});
const timeFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: TIME_ZONE,
});
const dateTimeFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: TIME_ZONE,
});

/** Jalali date, e.g. ۱۳ مهر ۱۴۰۵. */
export function formatDate(input: string | number | Date): string {
  const d = parse(input);
  return d ? dateFmt.format(d) : "";
}

/** Time of day in Asia/Tehran with Persian digits. */
export function formatTime(input: string | number | Date): string {
  const d = parse(input);
  return d ? timeFmt.format(d) : "";
}

/** Jalali date and time. */
export function formatDateTime(input: string | number | Date): string {
  const d = parse(input);
  return d ? dateTimeFmt.format(d) : "";
}

const relFmt = new Intl.RelativeTimeFormat("fa", { numeric: "auto" });

/** Relative time in Persian ("۳ دقیقه پیش", "دیروز"); falls back to a Jalali date after a month. */
export function relativeTime(input: string | number | Date, now: number = Date.now()): string {
  const d = parse(input);
  if (!d) return "";
  const diffSec = Math.round((d.getTime() - now) / 1000);
  const abs = Math.abs(diffSec);
  if (abs < 45) return "همین حالا";
  if (abs < 3600) return relFmt.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return relFmt.format(Math.round(diffSec / 3600), "hour");
  if (abs < 30 * 86400) return relFmt.format(Math.round(diffSec / 86400), "day");
  return formatDate(d);
}
