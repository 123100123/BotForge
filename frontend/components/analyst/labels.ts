import { fa, toFaDigits } from "@/lib/format";
import type {
  AnalysisAnomaly,
  AnalysisCheckSpec,
  AnalysisMetricSpec,
  AnalysisRunOut,
  InferredColumnType,
} from "@/lib/types";

export const TYPE_LABELS: Record<InferredColumnType, string> = {
  text: "متن",
  integer: "عدد صحیح",
  decimal: "عدد اعشاری",
  datetime: "تاریخ و زمان",
  boolean: "بله/خیر",
  empty: "خالی",
};

export const MEASURE_LABELS: Record<AnalysisMetricSpec["measure"], string> = {
  count: "تعداد",
  sum: "مجموع",
  avg: "میانگین",
  min: "کمترین",
  max: "بیشترین",
};

export const CHECK_LABELS: Record<AnalysisCheckSpec["kind"], string> = {
  outlier_high: "مقدار غیرعادی بالا",
  outlier_low: "مقدار غیرعادی پایین",
  threshold_above: "بیشتر از حد مجاز",
  threshold_below: "کمتر از حد مجاز",
  missing_values: "مقدار خالی",
};

export const SEVERITY_LABELS: Record<AnalysisAnomaly["severity"], string> = {
  info: "اطلاع",
  warning: "هشدار",
  critical: "بحرانی",
};

export const SEVERITY_VARIANT: Record<AnalysisAnomaly["severity"], "accent" | "warning" | "destructive"> = {
  info: "accent",
  warning: "warning",
  critical: "destructive",
};

export const STATUS_LABELS: Record<AnalysisRunOut["status"], string> = {
  ok: "موفق",
  schema_changed: "ساختار تغییر کرده",
  failed: "ناموفق",
};

export const STATUS_VARIANT: Record<AnalysisRunOut["status"], "success" | "warning" | "destructive"> = {
  ok: "success",
  schema_changed: "warning",
  failed: "destructive",
};

/** Largest file the backend accepts. */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export function fileSizeText(bytes: number): string {
  if (bytes < 1024) return `${fa(bytes)} بایت`;
  if (bytes < 1024 * 1024) return `${toFaDigits((bytes / 1024).toFixed(1).replace(".", "٫"))} کیلوبایت`;
  return `${toFaDigits((bytes / (1024 * 1024)).toFixed(1).replace(".", "٫"))} مگابایت`;
}

const FA_AR_DIGITS = /[۰-۹٠-٩]/g;

/** Parses a number typed with Persian, Arabic or ASCII digits; null for empty or invalid text. */
export function parseNumberInput(text: string): number | null {
  const ascii = text
    .replace(FA_AR_DIGITS, (d) => String(d.charCodeAt(0) >= 0x06f0 ? d.charCodeAt(0) - 0x06f0 : d.charCodeAt(0) - 0x0660))
    .replace(/[٫,]/g, ".")
    .replace(/[٬\s]/g, "")
    .trim();
  if (ascii === "") return null;
  const n = Number(ascii);
  return Number.isFinite(n) ? n : null;
}
