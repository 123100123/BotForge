/**
 * Conversion between the ISO 8601 strings the backend stores (UTC or with an offset) and the
 * Jalali DateObject the date picker works with. Wall-clock time is in the bot's IANA time zone
 * (the collection's `timezone`), Asia/Tehran by default.
 */
import DateObject from "react-date-object";
import gregorian from "react-date-object/calendars/gregorian";
import persian from "react-date-object/calendars/persian";
import gregorian_en from "react-date-object/locales/gregorian_en";
import persian_fa from "react-date-object/locales/persian_fa";

export const DEFAULT_TIME_ZONE = "Asia/Tehran";

function formatterFor(timeZone: string): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
  });
}

/** Wall-clock parts of an instant in `timeZone`. */
function wallParts(date: Date, timeZone: string): Record<string, number> {
  const p: Record<string, number> = {};
  for (const part of formatterFor(timeZone).formatToParts(date)) {
    if (part.type !== "literal") p[part.type] = Number(part.value);
  }
  return p;
}

/** Offset of `timeZone` from UTC, in minutes, at the given instant. */
function offsetMinutes(utcMs: number, timeZone: string): number {
  const p = wallParts(new Date(utcMs), timeZone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
  return Math.round((asUtc - Math.floor(utcMs / 60000) * 60000) / 60000);
}

/** ISO 8601 string -> Jalali DateObject showing time in `timeZone`; undefined for empty or invalid input. */
export function isoToJalali(iso: string, timeZone: string = DEFAULT_TIME_ZONE): DateObject | undefined {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return undefined;
  const p = wallParts(date, timeZone);
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

/** Jalali DateObject (wall-clock time in `timeZone`) -> ISO 8601 with that zone's UTC offset. */
export function jalaliToIso(value: DateObject, timeZone: string = DEFAULT_TIME_ZONE): string {
  const g = new DateObject(value).convert(gregorian, gregorian_en);
  const wallAsUtc = Date.UTC(g.year, g.month.number - 1, g.day, g.hour, g.minute);
  // The offset depends on the instant itself (daylight saving time); refine once.
  let offset = offsetMinutes(wallAsUtc, timeZone);
  offset = offsetMinutes(wallAsUtc - offset * 60000, timeZone);
  const sign = offset < 0 ? "-" : "+";
  const abs = Math.abs(offset);
  return `${g.year}-${pad(g.month.number)}-${pad(g.day)}T${pad(g.hour)}:${pad(g.minute)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}
