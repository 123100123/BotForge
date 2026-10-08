const DEFAULT_ZONE = "Asia/Tehran";

const cache = new Map<string, Intl.DateTimeFormat>();

function fmt(key: string, options: Intl.DateTimeFormatOptions, zone: string): Intl.DateTimeFormat {
  const k = `${key}|${zone}`;
  let f = cache.get(k);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { ...options, timeZone: zone });
    } catch {
      f = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { ...options, timeZone: DEFAULT_ZONE });
    }
    cache.set(k, f);
  }
  return f;
}

export interface JalaliParts {
  day: string;
  month: string;
  weekday: string;
  time: string;
}

/** The parts of a Jalali date for a date block: «۱۴»، «مهر»، «پنجشنبه»، «۱۸:۳۰» in the given zone. */
export function jalaliParts(iso: string | number, timeZone?: string): JalaliParts | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const zone = timeZone || DEFAULT_ZONE;
  const part = (f: Intl.DateTimeFormat, type: Intl.DateTimeFormatPartTypes) => f.formatToParts(d).find((p) => p.type === type)?.value ?? "";
  return {
    day: part(fmt("day", { day: "numeric" }, zone), "day"),
    month: part(fmt("month", { month: "long" }, zone), "month"),
    weekday: part(fmt("weekday", { weekday: "long" }, zone), "weekday"),
    time: fmt("time", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, zone).format(d),
  };
}

/** A stable key for the calendar day (Jalali) of a moment in the given zone, for grouping. */
export function dayKey(iso: string | number, timeZone?: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return fmt("daykey", { year: "numeric", month: "numeric", day: "numeric" }, timeZone || DEFAULT_ZONE).format(d);
}

/** «پنجشنبه ۱۴ مهر» for a day heading. */
export function dayHeading(iso: string | number, timeZone?: string): string {
  const p = jalaliParts(iso, timeZone);
  return p ? `${p.weekday} ${p.day} ${p.month}` : "";
}
