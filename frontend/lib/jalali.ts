/**
 * Conversion between the ISO 8601 strings the backend stores (UTC or with an offset) and the
 * Jalali DateObject the date picker works with. Wall-clock time is Asia/Tehran (+03:30; Iran has
 * no daylight saving time since 2022), the same zone lib/format.ts displays in.
 */
import DateObject from "react-date-object";
import gregorian from "react-date-object/calendars/gregorian";
import persian from "react-date-object/calendars/persian";
import gregorian_en from "react-date-object/locales/gregorian_en";
import persian_fa from "react-date-object/locales/persian_fa";

const TEHRAN_OFFSET = "+03:30";

const partsFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Tehran",
  hourCycle: "h23",
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
});

/** ISO 8601 string -> Jalali DateObject showing Tehran time; undefined for empty or invalid input. */
export function isoToJalali(iso: string): DateObject | undefined {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return undefined;
  const p: Record<string, number> = {};
  for (const part of partsFmt.formatToParts(date)) {
    if (part.type !== "literal") p[part.type] = Number(part.value);
  }
  return new DateObject({
    calendar: gregorian,
    locale: gregorian_en,
    year: p.year,
    month: p.month,
    day: p.day,
    hour: p.hour,
    minute: p.minute,
  }).convert(persian, persian_fa);
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Jalali DateObject (Tehran wall-clock time) -> ISO 8601 with the +03:30 offset. */
export function jalaliToIso(value: DateObject): string {
  const g = new DateObject(value).convert(gregorian, gregorian_en);
  return `${g.year}-${pad(g.month.number)}-${pad(g.day)}T${pad(g.hour)}:${pad(g.minute)}:00${TEHRAN_OFFSET}`;
}
