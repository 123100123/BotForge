import { useState } from "react";
import { Check, Minus } from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatDate, formatDateTime, formatNumber, relativeTime, toFaDigits } from "@/lib/format";
import type { FieldDef } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY = 86_400_000;

/** Recent datetimes read as relative time ("۳ ساعت پیش"), the rest as a Jalali date and time. */
export function DateTimeValue({
  value,
  timeZone,
  className,
  compact,
}: {
  value: string;
  timeZone?: string;
  className?: string;
  /** Older than a day: the date only (list columns of "when was it created"). */
  compact?: boolean;
}) {
  const [now] = useState(() => Date.now()); // fixed at mount: a list does not re-flow every minute
  const t = new Date(value).getTime();
  if (Number.isNaN(t)) return null;
  const full = formatDateTime(value, timeZone);
  const shown = compact ? formatDate(value) : full;
  const recent = Math.abs(now - t) < DAY;
  return (
    <time dateTime={value} title={recent || compact ? full : undefined} className={cn("whitespace-nowrap", className)}>
      {recent ? relativeTime(value, now) : shown}
    </time>
  );
}

export function BooleanValue({ value }: { value: boolean }) {
  return value ? (
    <span className="inline-flex items-center gap-1.5">
      <Check aria-hidden className="size-4 text-success" strokeWidth={1.75} />
      بله
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-fg-muted">
      <Minus aria-hidden className="size-4" strokeWidth={1.75} />
      خیر
    </span>
  );
}

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/** True when the column holds numbers (aligned at the end edge, tabular). */
export function isNumericField(field: FieldDef): boolean {
  return field.type === "integer" || field.type === "decimal";
}

function firstLine(text: string): string {
  const line = text.split(/\r?\n/).find((l) => l.trim() !== "");
  return (line ?? text).trim();
}

/** One stored value in a table cell: typed, single line, truncated (the drawer shows it in full). */
export function FieldCell({ field, value, timeZone }: { field: FieldDef; value: unknown; timeZone?: string }) {
  if (isEmpty(value)) return <span className="text-fg-muted">—</span>;
  switch (field.type) {
    case "integer":
    case "decimal":
      return <span className="tabular-nums">{typeof value === "number" ? formatNumber(value) : toFaDigits(String(value))}</span>;
    case "datetime":
      return <DateTimeValue value={String(value)} timeZone={timeZone} />;
    case "boolean":
      return <BooleanValue value={value === true} />;
    case "choice":
      return (
        <StatusBadge tone="neutral" marker>
          {String(value)}
        </StatusBadge>
      );
    case "phone":
      return (
        <span dir="ltr" className="inline-block">
          {toFaDigits(String(value))}
        </span>
      );
    case "long_text":
      return <span className="block truncate">{firstLine(String(value))}</span>;
    default:
      return <span className="block truncate">{String(value)}</span>;
  }
}

/** One stored value in full, for the drawer. */
export function FieldValue({ field, value, timeZone }: { field: FieldDef; value: unknown; timeZone?: string }) {
  if (isEmpty(value)) return <span className="text-fg-muted">—</span>;
  switch (field.type) {
    case "long_text":
      return <span className="break-words whitespace-pre-wrap">{String(value)}</span>;
    case "text":
      return <span className="break-words">{String(value)}</span>;
    case "datetime":
      return <time dateTime={String(value)}>{formatDateTime(String(value), timeZone)}</time>;
    default:
      return <FieldCell field={field} value={value} timeZone={timeZone} />;
  }
}

/** Plain text of a stored value (search). */
export function fieldPlainText(field: FieldDef, value: unknown, timeZone?: string): string {
  if (isEmpty(value)) return "";
  switch (field.type) {
    case "boolean":
      return value === true ? "بله" : "خیر";
    case "integer":
    case "decimal":
      return typeof value === "number" ? formatNumber(value) : toFaDigits(String(value));
    case "datetime":
      return formatDateTime(String(value), timeZone);
    case "phone":
      return toFaDigits(String(value));
    default:
      return String(value);
  }
}

/** Sort key of a stored value: numbers and datetimes compare by value, the rest as text. */
export function fieldSortValue(field: FieldDef, value: unknown): string | number | null {
  if (isEmpty(value)) return null;
  switch (field.type) {
    case "integer":
    case "decimal": {
      const n = typeof value === "number" ? value : Number(String(value));
      return Number.isFinite(n) ? n : null;
    }
    case "datetime": {
      const t = new Date(String(value)).getTime();
      return Number.isNaN(t) ? null : t;
    }
    case "boolean":
      return value === true ? 1 : 0;
    default:
      return String(value);
  }
}
