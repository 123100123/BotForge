import type {
  AnalysisProfileCreateIn,
  AnalysisProfileOut,
  AnalysisProfileUpdateIn,
  AnalysisRunIn,
  AnalysisRunOut,
  UploadOut,
  WorkbookInspection,
} from "@/lib/types";
import { ApiError } from "@/lib/errors";

/** Demo data for the Data Analyst: one profile, one run, and a fake inspection for any uploaded file. */

const inspection: WorkbookInspection = {
  signature: "demo-signature-1",
  row_limit_hit: false,
  sheets: [
    {
      name: "فروش",
      rows: 120,
      columns: [
        { name: "تاریخ", inferred_type: "datetime", non_null: 120, distinct: 30, sample: ["۱۴۰۴/۰۱/۰۱"], min: null, max: null, mean: null },
        { name: "محصول", inferred_type: "text", non_null: 120, distinct: 8, sample: ["چای", "قهوه"], min: null, max: null, mean: null },
        { name: "مبلغ", inferred_type: "integer", non_null: 118, distinct: 60, sample: ["120000"], min: "20000", max: "950000", mean: 310000 },
      ],
      sample_rows: [
        ["۱۴۰۴/۰۱/۰۱", "چای", "120000"],
        ["۱۴۰۴/۰۱/۰۲", "قهوه", "250000"],
      ],
    },
  ],
};

let uploads: UploadOut[] = [];
let profiles: AnalysisProfileOut[] | null = null;
let runs: AnalysisRunOut[] | null = null;

function seedProfiles(): AnalysisProfileOut[] {
  return [
    {
      id: "mock-profile-1",
      name: "گزارش فروش روزانه",
      signature: inspection.signature,
      sheet: "فروش",
      expected_columns: ["تاریخ", "محصول", "مبلغ"],
      metrics: [
        { id: "total", label: "مجموع فروش", measure: "sum", field: "مبلغ", group_by: null, group_kind: null, top_n: null },
        { id: "by_product", label: "فروش هر محصول", measure: "sum", field: "مبلغ", group_by: "محصول", group_kind: "field", top_n: 5 },
      ],
      checks: [
        { id: "high", label: "فروش غیرعادی بالا", kind: "outlier_high", field: "مبلغ", group_by: null, threshold: null },
      ],
      daily_report: true,
      created_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
      runs_count: 1,
    },
  ];
}

function seedRuns(): AnalysisRunOut[] {
  return [
    {
      id: "mock-run-1",
      profile_id: "mock-profile-1",
      upload_id: "mock-upload-1",
      filename: "sales.xlsx",
      status: "ok",
      submitted_by: null,
      created_at: new Date(Date.now() - 86_400_000).toISOString(),
      metrics: [
        { id: "total", label: "مجموع فروش", kind: "scalar", value: 37_200_000, unit: "تومان", series: null, rows: null, previous: null },
      ],
      anomalies: [
        { check_id: "high", label: "فروش غیرعادی بالا", field: "مبلغ", group: "قهوه", value: 950000, expected: 310000, severity: "warning" },
      ],
      narrative: "فروش کل در این فایل ۳۷٫۲ میلیون تومان است و یک فروش غیرعادی در محصول قهوه دیده شد.",
      schema_diff: null,
      error: null,
    },
  ];
}

function allProfiles(): AnalysisProfileOut[] {
  if (!profiles) profiles = seedProfiles();
  return profiles;
}

function allRuns(): AnalysisRunOut[] {
  if (!runs) runs = seedRuns();
  return runs;
}

export function uploadWorkbook(file: File): UploadOut {
  const out: UploadOut = {
    id: `mock-upload-${uploads.length + 2}`,
    filename: file.name,
    size: file.size,
    content_type: file.type || "application/octet-stream",
    sha256: "0".repeat(64),
    created_at: new Date().toISOString(),
    inspection,
  };
  uploads = [out, ...uploads];
  return out;
}

export function listUploads(): UploadOut[] {
  return uploads;
}

export function listAnalysisProfiles(): AnalysisProfileOut[] {
  return allProfiles();
}

function findProfile(profileId: string): AnalysisProfileOut {
  const p = allProfiles().find((x) => x.id === profileId);
  if (!p) throw new ApiError("not_found", "پروفایل تحلیل پیدا نشد.", 404);
  return p;
}

export function createAnalysisProfile(body: AnalysisProfileCreateIn): AnalysisProfileOut {
  const created: AnalysisProfileOut = {
    ...seedProfiles()[0],
    id: `mock-profile-${allProfiles().length + 1}`,
    name: body.name ?? "پروفایل جدید",
    daily_report: body.daily_report ?? false,
    created_at: new Date().toISOString(),
    runs_count: 0,
  };
  profiles = [created, ...allProfiles()];
  return created;
}

export function updateAnalysisProfile(profileId: string, body: AnalysisProfileUpdateIn): AnalysisProfileOut {
  const p = findProfile(profileId);
  Object.assign(p, body);
  return { ...p };
}

export function runAnalysis(profileId: string, body: AnalysisRunIn): AnalysisRunOut {
  const p = findProfile(profileId);
  const upload = uploads.find((u) => u.id === body.upload_id);
  const run: AnalysisRunOut = {
    ...seedRuns()[0],
    id: `mock-run-${allRuns().length + 1}`,
    profile_id: p.id,
    upload_id: body.upload_id,
    filename: upload?.filename ?? null,
    created_at: new Date().toISOString(),
    narrative: body.narrative ? seedRuns()[0].narrative : null,
  };
  runs = [run, ...allRuns()];
  p.runs_count += 1;
  return run;
}

export function listAnalysisRuns(profileId?: string): AnalysisRunOut[] {
  return allRuns().filter((r) => !profileId || r.profile_id === profileId);
}
