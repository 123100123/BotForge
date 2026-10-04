import { formatDateTime, formatNumber, toFaDigits } from "@/lib/format";
import type { FieldDef } from "@/lib/types";

export type FormValue = string | boolean;
export type FormValues = Record<string, FormValue>;

export const FIELD_TYPE_LABELS: Record<FieldDef["type"], string> = {
  text: "متن کوتاه",
  long_text: "متن بلند",
  integer: "عدد صحیح",
  decimal: "عدد",
  datetime: "تاریخ و ساعت",
  boolean: "بله/خیر",
  choice: "انتخابی",
  phone: "تلفن",
};

/** Initial form values: the record's stored data when editing, otherwise each field's default. */
export function initialValues(fields: FieldDef[], data?: Record<string, unknown>): FormValues {
  const values: FormValues = {};
  for (const f of fields) {
    const stored = data?.[f.key];
    if (f.type === "boolean") {
      values[f.key] = data ? stored === true : f.default === "true";
    } else if (stored === null || stored === undefined) {
      values[f.key] = data ? "" : (f.default ?? "");
    } else if (f.type === "integer" || f.type === "decimal" || f.type === "phone") {
      values[f.key] = toFaDigits(String(stored));
    } else {
      values[f.key] = String(stored);
    }
  }
  return values;
}

/** The `data` object of a create/patch request. Numbers go as typed (the backend reads Persian digits). */
export function toPayload(fields: FieldDef[], values: FormValues): Record<string, unknown> {
  const data: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.key];
    data[f.key] = typeof v === "string" ? v.trim() : v;
  }
  return data;
}

/**
 * Splits the backend's `invalid_record` messages into per-field messages. Each message starts with
 * the field label in «» (backend/app/botspec/records.py); anything else stays a general error.
 */
export function splitFieldErrors(
  fields: FieldDef[],
  details: unknown,
): { byField: Record<string, string>; general: string[] } {
  const byField: Record<string, string> = {};
  const general: string[] = [];
  const list = Array.isArray(details) ? details.filter((d): d is string => typeof d === "string") : [];
  for (const message of list) {
    const field = fields.find((f) => message.startsWith(`«${f.label}»`));
    if (field && !byField[field.key]) byField[field.key] = message;
    else general.push(message);
  }
  return { byField, general };
}

/** Plain-text rendering of one stored value for table cells. */
export function formatCell(field: FieldDef, value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  switch (field.type) {
    case "boolean":
      return value === true ? "بله" : "خیر";
    case "integer":
    case "decimal":
      return typeof value === "number" ? formatNumber(value) : toFaDigits(String(value));
    case "datetime":
      return formatDateTime(String(value));
    case "phone":
      return toFaDigits(String(value));
    default:
      return String(value);
  }
}
