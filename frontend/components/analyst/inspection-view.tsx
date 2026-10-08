"use client";

import { useState } from "react";
import { TriangleAlertIcon } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fa } from "@/lib/format";
import type { ColumnProfile, SheetProfile, UploadOut } from "@/lib/types";
import { fileSizeText, TYPE_ICONS, TYPE_LABELS } from "./labels";

const SAMPLES = 3;

function FillRate({ column, rows }: { column: ColumnProfile; rows: number }) {
  const pct = rows > 0 ? Math.round((column.non_null / rows) * 100) : 0;
  return (
    <span className="flex items-center gap-2">
      <span aria-hidden className="h-1.5 w-12 shrink-0 rounded-xs bg-border">
        <span className="block h-full rounded-xs bg-chart-1" style={{ width: `${pct}%` }} />
      </span>
      <span>
        {fa(pct)}٪ <span className="text-fg-muted">پر</span>
      </span>
    </span>
  );
}

function ColumnRow({ column, rows }: { column: ColumnProfile; rows: number }) {
  const Icon = TYPE_ICONS[column.inferred_type] ?? TYPE_ICONS.text;
  const samples = (column.sample ?? []).slice(0, SAMPLES);
  return (
    <li className="grid gap-x-4 gap-y-1 border-t border-border px-4 py-3 text-small sm:grid-cols-[minmax(0,1.2fr)_9rem_9rem_minmax(0,1.6fr)] sm:items-center">
      <span className="font-medium text-fg">
        <bdi>{column.name}</bdi>
      </span>
      <span className="inline-flex items-center gap-1.5 text-fg-secondary">
        <Icon aria-hidden className="size-4 shrink-0 text-fg-muted" strokeWidth={1.75} />
        {TYPE_LABELS[column.inferred_type] ?? column.inferred_type}
      </span>
      <FillRate column={column} rows={rows} />
      <span className="text-fg-secondary">
        {samples.length === 0 ? (
          <span className="text-fg-muted">بدون نمونه</span>
        ) : (
          samples.map((s, i) => (
            <span key={i}>
              {i > 0 && "، "}
              <bdi>{s}</bdi>
            </span>
          ))
        )}
      </span>
    </li>
  );
}

function ColumnList({ sheet }: { sheet: SheetProfile }) {
  const columns = sheet.columns ?? [];
  if (columns.length === 0) return <p className="p-4 text-small text-fg-muted">این برگه ستونی ندارد.</p>;
  return (
    <div className="overflow-hidden rounded-sm border border-border">
      <div aria-hidden className="hidden grid-cols-[minmax(0,1.2fr)_9rem_9rem_minmax(0,1.6fr)] gap-x-4 bg-surface-sunken px-4 py-2 text-caption text-fg-muted sm:grid">
        <span>ستون</span>
        <span>نوع داده</span>
        <span>پر بودن</span>
        <span>نمونه</span>
      </div>
      <ul aria-label={`ستون‌های برگهٔ ${sheet.name}`} className="-mt-px">
        {columns.map((c) => (
          <ColumnRow key={c.name} column={c} rows={sheet.rows} />
        ))}
      </ul>
    </div>
  );
}

/**
 * Step 2, the structure of an upload: one tab per sheet, and per column its name, detected type, how full it
 * is and a few sample values. The inspection detects types only, so nothing here says what a column means.
 */
export function InspectionView({ upload }: { upload: UploadOut }) {
  const sheets = upload.inspection?.sheets ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const active = sheets.find((s) => s.name === chosen)?.name ?? sheets[0]?.name;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-small text-fg-muted">
        <bdi dir="ltr">{upload.filename}</bdi> · {fileSizeText(upload.size)} · {fa(sheets.length)} برگه
      </p>
      {upload.inspection?.row_limit_hit && (
        <p role="status" className="flex items-start gap-2 rounded-sm bg-warning-soft p-3 text-small text-warning-text">
          <TriangleAlertIcon aria-hidden className="mt-1 size-4 shrink-0" strokeWidth={1.75} />
          این فایل بیش از حد مجاز ردیف دارد؛ فقط بخش اول آن خوانده شد.
        </p>
      )}
      {sheets.length === 0 ? (
        <p className="text-small text-fg-muted">برگه‌ای در این فایل پیدا نشد.</p>
      ) : (
        <Tabs value={active} onValueChange={setChosen}>
          <TabsList aria-label="برگه‌های فایل">
            {sheets.map((s) => (
              <TabsTrigger key={s.name} value={s.name} className="min-h-11">
                <bdi>{s.name}</bdi>
                <span className="text-caption text-fg-muted">{fa(s.rows)} ردیف</span>
              </TabsTrigger>
            ))}
          </TabsList>
          {sheets.map((s) => (
            <TabsContent key={s.name} value={s.name}>
              <ColumnList sheet={s} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}
