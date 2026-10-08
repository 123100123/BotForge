import {
  CalendarIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  HashIcon,
  InfoIcon,
  OctagonAlertIcon,
  ToggleLeftIcon,
  TriangleAlertIcon,
  TypeIcon,
  type LucideIcon,
} from "lucide-react";
import { fa, toFaDigits } from "@/lib/format";
import type { AnalysisAnomaly, AnalysisRunOut, InferredColumnType } from "@/lib/types";

/** The kind of values a column holds, as the upload inspection detects it (types only, never meaning). */
export const TYPE_LABELS: Record<InferredColumnType, string> = {
  text: "متن",
  integer: "عدد صحیح",
  decimal: "عدد اعشاری",
  datetime: "تاریخ و زمان",
  boolean: "بله/خیر",
  empty: "خالی",
};

export const TYPE_ICONS: Record<InferredColumnType, LucideIcon> = {
  text: TypeIcon,
  integer: HashIcon,
  decimal: HashIcon,
  datetime: CalendarIcon,
  boolean: ToggleLeftIcon,
  empty: CircleDashedIcon,
};

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

export const SEVERITY_LABELS: Record<AnalysisAnomaly["severity"], string> = {
  info: "اطلاع",
  warning: "هشدار",
  critical: "بحرانی",
};

export const SEVERITY_TONE: Record<AnalysisAnomaly["severity"], Tone> = { info: "info", warning: "warning", critical: "danger" };

export const SEVERITY_ICONS: Record<AnalysisAnomaly["severity"], LucideIcon> = {
  info: InfoIcon,
  warning: TriangleAlertIcon,
  critical: OctagonAlertIcon,
};

export const STATUS_LABELS: Record<AnalysisRunOut["status"], string> = {
  ok: "موفق",
  schema_changed: "ساختار تغییر کرده",
  failed: "ناموفق",
};

export const STATUS_TONE: Record<AnalysisRunOut["status"], Tone> = { ok: "success", schema_changed: "warning", failed: "danger" };

export const STATUS_ICONS: Record<AnalysisRunOut["status"], LucideIcon> = {
  ok: CircleCheckIcon,
  schema_changed: TriangleAlertIcon,
  failed: CircleXIcon,
};

/** Largest file the backend accepts. */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

/** Error code of the per-account daily limit on assistant calls (profile drafts and run summaries). */
export const DAILY_CAP_CODE = "analysis_daily_cap";

export function fileSizeText(bytes: number): string {
  if (bytes < 1024) return `${fa(bytes)} بایت`;
  if (bytes < 1024 * 1024) return `${toFaDigits((bytes / 1024).toFixed(1).replace(".", "٫"))} کیلوبایت`;
  return `${toFaDigits((bytes / (1024 * 1024)).toFixed(1).replace(".", "٫"))} مگابایت`;
}

/** Who sent a file: the panel (null) or a staff member through Telegram (`tg:<id>`). */
export function submitterText(submittedBy: string | null): string {
  if (!submittedBy) return "از همین پنل";
  if (submittedBy.startsWith("tg:")) return "کارمند، از تلگرام";
  return submittedBy;
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
