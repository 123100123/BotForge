"use client";

import { useState } from "react";
import { InfoNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fa, formatNumber } from "@/lib/format";
import type { ColumnProfile, SheetProfile, UploadOut } from "@/lib/types";
import { fileSizeText, TYPE_LABELS } from "./labels";

function cell(value: unknown) {
  return value === null || value === undefined || value === "" ? <span className="text-muted-foreground">-</span> : <bdi>{String(value)}</bdi>;
}

function ColumnTable({ columns }: { columns: ColumnProfile[] }) {
  if (columns.length === 0) return <p className="text-sm text-muted-foreground">این برگه ستونی ندارد.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[40rem] text-start text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            {["ستون", "نوع", "غیرخالی", "یکتا", "کمترین", "بیشترین", "میانگین", "نمونه"].map((h) => (
              <th key={h} scope="col" className="px-3 py-2 text-start font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {columns.map((c) => (
            <tr key={c.name} className="border-t align-top">
              <th scope="row" className="px-3 py-2 text-start font-medium whitespace-nowrap">
                <bdi>{c.name}</bdi>
              </th>
              <td className="px-3 py-2">
                <Badge variant="accent">{TYPE_LABELS[c.inferred_type] ?? c.inferred_type}</Badge>
              </td>
              <td className="px-3 py-2">{fa(c.non_null)}</td>
              <td className="px-3 py-2">{fa(c.distinct)}</td>
              <td className="px-3 py-2">{cell(c.min)}</td>
              <td className="px-3 py-2">{cell(c.max)}</td>
              <td className="px-3 py-2">{c.mean === null || c.mean === undefined ? cell(null) : formatNumber(c.mean)}</td>
              <td className="max-w-56 px-3 py-2 text-muted-foreground">
                {c.sample && c.sample.length > 0 ? c.sample.slice(0, 3).map((s, i) => (
                  <span key={i}>
                    {i > 0 && "، "}
                    <bdi>{s}</bdi>
                  </span>
                )) : cell(null)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SampleRows({ sheet }: { sheet: SheetProfile }) {
  const rows = sheet.sample_rows ?? [];
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">ردیف نمونه‌ای وجود ندارد.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-max text-start text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            {sheet.columns.map((c) => (
              <th key={c.name} scope="col" className="px-3 py-2 text-start font-medium whitespace-nowrap">
                <bdi>{c.name}</bdi>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-t">
              {sheet.columns.map((c) => (
                <td key={c.name} className="px-3 py-2 whitespace-nowrap">
                  {cell(row[c.name])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The deterministic inspection of an upload: one tab per sheet with its column table and sample rows. */
export function InspectionView({ upload, children }: { upload: UploadOut; children?: React.ReactNode }) {
  const sheets = upload.inspection?.sheets ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const active = sheets.find((s) => s.name === chosen)?.name ?? sheets[0]?.name;

  return (
    <Card className="gap-4 py-5">
      <CardHeader className="gap-1">
        <CardTitle className="text-base">
          بررسی فایل <bdi>{upload.filename}</bdi>
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {fileSizeText(upload.size)} · {fa(sheets.length)} برگه
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {upload.inspection?.row_limit_hit && (
          <InfoNote tone="warning">این فایل بیش از حد مجاز ردیف دارد؛ فقط بخش اول آن بررسی شد.</InfoNote>
        )}
        {sheets.length === 0 ? (
          <p className="text-sm text-muted-foreground">برگه‌ای در این فایل پیدا نشد.</p>
        ) : (
          <Tabs value={active} onValueChange={setChosen}>
            <TabsList aria-label="برگه‌های فایل">
              {sheets.map((s) => (
                <TabsTrigger key={s.name} value={s.name}>
                  <bdi>{s.name}</bdi>
                  <span className="text-xs text-muted-foreground">{fa(s.rows)} ردیف</span>
                </TabsTrigger>
              ))}
            </TabsList>
            {sheets.map((s) => (
              <TabsContent key={s.name} value={s.name} className="flex flex-col gap-4">
                <section className="flex flex-col gap-2">
                  <h4 className="text-sm font-semibold">ستون‌ها</h4>
                  <ColumnTable columns={s.columns ?? []} />
                </section>
                <section className="flex flex-col gap-2">
                  <h4 className="text-sm font-semibold">نمونهٔ ردیف‌ها</h4>
                  <SampleRows sheet={s} />
                </section>
              </TabsContent>
            ))}
          </Tabs>
        )}
        {children}
      </CardContent>
    </Card>
  );
}
