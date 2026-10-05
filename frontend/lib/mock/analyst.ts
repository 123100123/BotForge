import type {
  AnalysisProfileCreateIn,
  AnalysisProfileOut,
  AnalysisProfileUpdateIn,
  AnalysisRunIn,
  AnalysisRunOut,
  SchemaDiff,
  UploadOut,
  WorkbookInspection,
} from "@/lib/types";
import { ApiError } from "@/lib/errors";

/**
 * Demo data for the Data Analyst. It exercises every state of the screen: an upload matching the demo profile, an
 * upload with a changed layout (running the profile on it gives `schema_changed`), one ok run and one schema_changed run.
 */

const DAY = 86_400_000;
const daysAgo = (n: number) => new Date(Date.now() - n * DAY).toISOString();

const salesInspection: WorkbookInspection = {
  signature: "demo-signature-1",
  row_limit_hit: false,
  sheets: [
    {
      name: "فروش",
      rows: 120,
      columns: [
        { name: "تاریخ", inferred_type: "datetime", non_null: 120, distinct: 30, sample: ["۱۴۰۴/۰۱/۰۱", "۱۴۰۴/۰۱/۰۲"], min: "۱۴۰۴/۰۱/۰۱", max: "۱۴۰۴/۰۱/۳۰", mean: null },
        { name: "محصول", inferred_type: "text", non_null: 120, distinct: 8, sample: ["چای", "قهوه", "شکلات"], min: null, max: null, mean: null },
        { name: "تعداد", inferred_type: "integer", non_null: 120, distinct: 12, sample: ["2", "5"], min: "1", max: "24", mean: 4.6 },
        { name: "مبلغ", inferred_type: "integer", non_null: 118, distinct: 60, sample: ["120000", "250000"], min: "20000", max: "950000", mean: 310000 },
      ],
      sample_rows: [
        ["۱۴۰۴/۰۱/۰۱", "چای", "2", "120000"],
        ["۱۴۰۴/۰۱/۰۲", "قهوه", "5", "250000"],
        ["۱۴۰۴/۰۱/۰۲", "شکلات", "1", "45000"],
      ],
    },
    {
      name: "هزینه‌ها",
      rows: 14,
      columns: [
        { name: "شرح", inferred_type: "text", non_null: 14, distinct: 9, sample: ["اجاره", "برق"], min: null, max: null, mean: null },
        { name: "مبلغ", inferred_type: "decimal", non_null: 13, distinct: 13, sample: ["1500000.5"], min: "80000", max: "9000000", mean: 1_240_000.5 },
        { name: "توضیح", inferred_type: "empty", non_null: 0, distinct: 0, sample: [], min: null, max: null, mean: null },
      ],
      sample_rows: [
        ["اجاره", "9000000", ""],
        ["برق", "350000", ""],
      ],
    },
  ],
};

/** The sales sheet after someone renamed "مبلغ" to "قیمت" and added a "تخفیف" column. */
const changedInspection: WorkbookInspection = {
  signature: "demo-signature-2",
  row_limit_hit: false,
  sheets: [
    {
      name: "فروش",
      rows: 64,
      columns: [
        { name: "تاریخ", inferred_type: "datetime", non_null: 64, distinct: 20, sample: ["۱۴۰۴/۰۲/۰۱"], min: null, max: null, mean: null },
        { name: "محصول", inferred_type: "text", non_null: 64, distinct: 7, sample: ["چای", "قهوه"], min: null, max: null, mean: null },
        { name: "تعداد", inferred_type: "integer", non_null: 64, distinct: 9, sample: ["3"], min: "1", max: "15", mean: 3.9 },
        { name: "قیمت", inferred_type: "integer", non_null: 64, distinct: 40, sample: ["135000"], min: "20000", max: "800000", mean: 290000 },
        { name: "تخفیف", inferred_type: "decimal", non_null: 20, distinct: 4, sample: ["0.1"], min: "0", max: "0.3", mean: 0.12 },
      ],
      sample_rows: [["۱۴۰۴/۰۲/۰۱", "چای", "3", "135000", "0.1"]],
    },
  ],
};

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function seedUploads(): UploadOut[] {
  return [
    {
      id: "mock-upload-2",
      filename: "sales-new-format.xlsx",
      size: 48_120,
      content_type: XLSX,
      sha256: "1".repeat(64),
      created_at: daysAgo(0.2),
      inspection: changedInspection,
    },
    {
      id: "mock-upload-1",
      filename: "sales.xlsx",
      size: 52_340,
      content_type: XLSX,
      sha256: "0".repeat(64),
      created_at: daysAgo(1),
      inspection: salesInspection,
    },
  ];
}

function seedProfiles(): AnalysisProfileOut[] {
  return [
    {
      id: "mock-profile-1",
      name: "گزارش فروش روزانه",
      signature: salesInspection.signature,
      sheet: "فروش",
      expected_columns: ["تاریخ", "محصول", "تعداد", "مبلغ"],
      metrics: [
        { id: "total", label: "مجموع فروش", measure: "sum", field: "مبلغ", group_by: null, group_kind: null, top_n: null },
        { id: "by_day", label: "فروش هر روز", measure: "sum", field: "مبلغ", group_by: "تاریخ", group_kind: "day", top_n: null },
        { id: "by_product", label: "فروش هر محصول", measure: "sum", field: "مبلغ", group_by: "محصول", group_kind: "field", top_n: 5 },
      ],
      checks: [
        { id: "high", label: "فروش غیرعادی بالا", kind: "outlier_high", field: "مبلغ", group_by: null, threshold: null },
        { id: "min_qty", label: "تعداد کمتر از حد انتظار", kind: "threshold_below", field: "تعداد", group_by: "محصول", threshold: 2 },
      ],
      daily_report: true,
      created_at: daysAgo(3),
      runs_count: 2,
    },
  ];
}

function okRun(
  id: string,
  profileId: string,
  upload: Pick<UploadOut, "id" | "filename">,
  createdAt: string,
  narrative: boolean,
): AnalysisRunOut {
  return {
    id,
    profile_id: profileId,
    upload_id: upload.id,
    filename: upload.filename,
    status: "ok",
    submitted_by: null,
    created_at: createdAt,
    metrics: [
      { id: "total", label: "مجموع فروش", kind: "scalar", value: 37_200_000, unit: "تومان", series: null, rows: null, previous: 33_100_000 },
      {
        id: "by_day",
        label: "فروش هر روز",
        kind: "series",
        value: null,
        unit: "تومان",
        series: [
          { label: "۱", value: 1_100_000 },
          { label: "۲", value: 1_450_000 },
          { label: "۳", value: 980_000 },
          { label: "۴", value: 1_720_000 },
          { label: "۵", value: 1_300_000 },
        ],
        rows: null,
        previous: null,
      },
      {
        id: "by_product",
        label: "فروش هر محصول",
        kind: "breakdown",
        value: null,
        unit: "تومان",
        series: [
          { label: "قهوه", value: 15_400_000 },
          { label: "چای", value: 11_900_000 },
          { label: "شکلات", value: 6_300_000 },
          { label: "شیرینی", value: 3_600_000 },
        ],
        rows: null,
        previous: null,
      },
    ],
    anomalies: [
      { check_id: "high", label: "فروش غیرعادی بالا", field: "مبلغ", group: "قهوه", value: 950_000, expected: 310_000, severity: "warning" },
      { check_id: "min_qty", label: "تعداد کمتر از حد انتظار", field: "تعداد", group: "شیرینی", value: 1, expected: 2, severity: "info" },
    ],
    narrative: narrative
      ? "فروش کل در این فایل ۳۷٫۲ میلیون تومان است، حدود ۱۲٪ بیشتر از فایل قبلی. قهوه با نزدیک به ۴۱٪ سهم، پرفروش‌ترین محصول است و یک فروش غیرعادی در همین محصول دیده شد."
      : null,
    schema_diff: null,
    error: null,
  };
}

function schemaChangedRun(
  id: string,
  profileId: string,
  upload: Pick<UploadOut, "id" | "filename">,
  createdAt: string,
  diff: SchemaDiff,
): AnalysisRunOut {
  return {
    id,
    profile_id: profileId,
    upload_id: upload.id,
    filename: upload.filename,
    status: "schema_changed",
    submitted_by: null,
    created_at: createdAt,
    metrics: [],
    anomalies: [],
    narrative: null,
    schema_diff: diff,
    error: null,
  };
}

let uploads: UploadOut[] = seedUploads();
let profiles: AnalysisProfileOut[] = seedProfiles();
let runs: AnalysisRunOut[] = [
  schemaChangedRun("mock-run-2", "mock-profile-1", { id: "mock-upload-2", filename: "sales-new-format.xlsx" }, daysAgo(0.1), {
    missing: ["مبلغ"],
    new: ["قیمت", "تخفیف"],
  }),
  okRun("mock-run-1", "mock-profile-1", { id: "mock-upload-1", filename: "sales.xlsx" }, daysAgo(1), true),
];

export function uploadWorkbook(file: File): UploadOut {
  const out: UploadOut = {
    id: `mock-upload-${uploads.length + 1}`,
    filename: file.name,
    size: file.size,
    content_type: file.type || "application/octet-stream",
    sha256: "0".repeat(64),
    created_at: new Date().toISOString(),
    inspection: salesInspection,
  };
  uploads = [out, ...uploads];
  return out;
}

export function listUploads(): UploadOut[] {
  return uploads;
}

export function listAnalysisProfiles(): AnalysisProfileOut[] {
  return profiles;
}

function findProfile(profileId: string): AnalysisProfileOut {
  const p = profiles.find((x) => x.id === profileId);
  if (!p) throw new ApiError("not_found", "پروفایل تحلیل پیدا نشد.", 404);
  return p;
}

function findUpload(uploadId: string): UploadOut {
  const u = uploads.find((x) => x.id === uploadId);
  if (!u) throw new ApiError("not_found", "فایل پیدا نشد.", 404);
  return u;
}

export function createAnalysisProfile(body: AnalysisProfileCreateIn): AnalysisProfileOut {
  const upload = findUpload(body.upload_id);
  const sheet = upload.inspection.sheets[0];
  const columns = sheet?.columns ?? [];
  const numeric = columns.find((c) => c.inferred_type === "integer" || c.inferred_type === "decimal");
  const created: AnalysisProfileOut = {
    id: `mock-profile-${profiles.length + 1}`,
    name: body.name?.trim() || "پروفایل جدید",
    signature: upload.inspection.signature,
    sheet: sheet?.name ?? "",
    expected_columns: columns.map((c) => c.name),
    metrics: numeric
      ? [{ id: "total", label: `مجموع ${numeric.name}`, measure: "sum", field: numeric.name, group_by: null, group_kind: null, top_n: null }]
      : [{ id: "rows", label: "تعداد ردیف‌ها", measure: "count", field: null, group_by: null, group_kind: null, top_n: null }],
    checks: numeric
      ? [{ id: "high", label: `${numeric.name} غیرعادی بالا`, kind: "outlier_high", field: numeric.name, group_by: null, threshold: null }]
      : [],
    daily_report: body.daily_report ?? false,
    created_at: new Date().toISOString(),
    runs_count: 0,
  };
  profiles = [created, ...profiles];
  return created;
}

export function updateAnalysisProfile(profileId: string, body: AnalysisProfileUpdateIn): AnalysisProfileOut {
  const p = findProfile(profileId);
  Object.assign(p, body);
  return { ...p };
}

export function runAnalysis(profileId: string, body: AnalysisRunIn): AnalysisRunOut {
  const p = findProfile(profileId);
  const upload = findUpload(body.upload_id);
  const id = `mock-run-${runs.length + 1}`;
  const now = new Date().toISOString();
  let run: AnalysisRunOut;
  if (upload.inspection.signature !== p.signature) {
    const cols = upload.inspection.sheets.find((s) => s.name === p.sheet)?.columns.map((c) => c.name) ?? [];
    run = schemaChangedRun(id, p.id, upload, now, {
      missing: p.expected_columns.filter((c) => !cols.includes(c)),
      new: cols.filter((c) => !p.expected_columns.includes(c)),
    });
  } else {
    run = okRun(id, p.id, upload, now, body.narrative ?? false);
  }
  runs = [run, ...runs];
  p.runs_count += 1;
  return run;
}

export function listAnalysisRuns(profileId?: string): AnalysisRunOut[] {
  return runs.filter((r) => !profileId || r.profile_id === profileId);
}
