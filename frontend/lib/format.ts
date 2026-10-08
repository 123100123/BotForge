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

/**
 * Owner-facing text must never show requirement codes (R1, R12). Removes them, unwraps a parenthesized
 * detail that followed one («R3 (ظرفیت از ۱۰ به ۱۲)» -> «ظرفیت از ۱۰ به ۱۲») and tidies the punctuation left behind.
 */
export function stripRequirementCodes(text: string): string {
  if (!/\bR\d+\b/.test(text)) return text;
  return text
    .replace(/\bR\d+\b[ \t]*:?[ \t]*\(([^()]*)\)/g, "$1")
    .replace(/\bR\d+\b[ \t]*:?/g, "")
    .replace(/\([ \t]*\)/g, "")
    .replace(/([,،])[ \t]*(?=[,،])/g, "")
    .replace(/[ \t]+([,،:؛.])/g, "$1")
    .replace(/:[ \t]*(?=\n|$)/gm, ":")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/^[ \t]*[,،][ \t]*/gm, "")
    .replace(/:[ \t]*[,،]+/g, ":")
    .replace(/[,،][ \t]*$/gm, "")
    .replace(/[ \t]+$/gm, "")
    .trim();
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

const zonedFormats = new Map<string, Intl.DateTimeFormat>();

/** Jalali date and time, in Asia/Tehran unless `timeZone` (an IANA zone) is given. */
export function formatDateTime(input: string | number | Date, timeZone?: string): string {
  const d = parse(input);
  if (!d) return "";
  if (!timeZone || timeZone === TIME_ZONE) return dateTimeFmt.format(d);
  let fmt = zonedFormats.get(timeZone);
  if (!fmt) {
    try {
      fmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone,
      });
    } catch {
      fmt = dateTimeFmt; // unknown zone name: fall back to the default zone
    }
    zonedFormats.set(timeZone, fmt);
  }
  return fmt.format(d);
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

/** A duration as Persian words, e.g. 100000 ms -> «۱ دقیقه و ۴۰ ثانیه»; under a second reads «کمتر از ۱ ثانیه». */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  if (total < 1) return "کمتر از ۱ ثانیه";
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  if (minutes === 0) return `${fa(seconds)} ثانیه`;
  if (seconds === 0) return `${fa(minutes)} دقیقه`;
  return `${fa(minutes)} دقیقه و ${fa(seconds)} ثانیه`;
}
