"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { fa, formatDateTime } from "@/lib/format";
import type { AnalysisProfileOut, AnalysisRunOut } from "@/lib/types";
import { RunStatusBadge } from "./run-report";
import { submitterText } from "./labels";

function anomalyText(run: AnalysisRunOut): string {
  if (run.status !== "ok") return "—";
  const n = run.anomalies?.length ?? 0;
  return n === 0 ? "بدون مورد" : `${fa(n)} مورد`;
}

/**
 * Every run, newest first: file, profile, who sent it, when (Jalali), status and how many findings. A table
 * from 768px up, a list of rows below it. Opening a run goes to `hrefFor(run)`.
 */
export function RunHistory({
  runs,
  profiles,
  hrefFor,
}: {
  runs: AnalysisRunOut[];
  profiles: AnalysisProfileOut[];
  hrefFor: (run: AnalysisRunOut) => string;
}) {
  const router = useRouter();
  const profileName = (run: AnalysisRunOut) => profiles.find((p) => p.id === run.profile_id)?.name ?? "پروفایل حذف‌شده";
  const fileName = (run: AnalysisRunOut) => (run.filename ? <bdi dir="ltr">{run.filename}</bdi> : "فایل حذف‌شده");

  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface">
      <table className="hidden w-full text-small md:table">
        <caption className="sr-only">سابقهٔ تحلیل‌ها</caption>
        <thead className="bg-surface-sunken text-caption text-fg-muted">
          <tr>
            {["فایل", "پروفایل", "ارسال‌کننده", "زمان", "وضعیت", "موارد قابل توجه"].map((h) => (
              <th key={h} scope="col" className="px-4 py-2.5 text-start font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} onClick={() => router.push(hrefFor(r))} className="cursor-pointer border-t border-border transition-colors duration-fast hover:bg-surface-sunken">
              <td className="max-w-56 truncate px-4 py-3 font-medium text-fg">
                <Link href={hrefFor(r)} className="rounded-xs hover:underline">
                  {fileName(r)}
                </Link>
              </td>
              <td className="px-4 py-3 text-fg-secondary">{profileName(r)}</td>
              <td className="px-4 py-3 text-fg-secondary">{submitterText(r.submitted_by)}</td>
              <td className="px-4 py-3 whitespace-nowrap text-fg-secondary">{formatDateTime(r.created_at)}</td>
              <td className="px-4 py-3">
                <RunStatusBadge status={r.status} />
              </td>
              <td className="px-4 py-3 text-fg-secondary">{anomalyText(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="md:hidden">
        {runs.map((r) => (
          <li key={r.id} className="border-t border-border first:border-t-0">
            <Link href={hrefFor(r)} className="flex flex-col gap-2 p-4 transition-colors duration-fast hover:bg-surface-sunken">
              <span className="min-w-0 truncate text-body font-medium text-fg">{fileName(r)}</span>
              <span className="text-small text-fg-secondary">
                {profileName(r)} · {formatDateTime(r.created_at)}
              </span>
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-small text-fg-secondary">
                <RunStatusBadge status={r.status} />
                <span>{anomalyText(r)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
