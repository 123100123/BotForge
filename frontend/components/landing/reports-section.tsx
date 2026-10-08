import { CircleCheckIcon, TriangleAlertIcon } from "lucide-react";
import { MetricStrip } from "@/components/app/metric-strip";
import { BarChart } from "@/components/charts/bar-chart";
import { StatusBadge } from "@/components/ui/status-badge";
import { cn } from "@/lib/utils";
import { BUSINESS_NAME, REPORT_METRICS, REPORT_SERIES, SHEET_FILE, SHEET_ROWS } from "./data";
import { CONTAINER } from "./nav";

const POINTS = [
  {
    title: "هر روز، بی‌آنکه بپرسید",
    text: "خلاصهٔ روز در پنل می‌ماند و در ساعتی که تعیین کنید به تلگرام مدیر هم می‌رسد.",
  },
  {
    title: "اکسل هر روز، با همان قاعده",
    text: "فایل اکسل را بفرستید. دستیار هر بار آن را با همان پروفایل ستون‌ها تحلیل می‌کند و موارد غیرعادی را نشان می‌دهد.",
  },
  {
    title: "کارهای روزمره بدون هوش مصنوعی",
    text: "سفارش، رزرو و گزارش با قاعده‌های ثابت اجرا می‌شوند، پس قابل‌پیش‌بینی‌اند. هوش مصنوعی برای ساختن، تغییر دادن و پاسخ به پرسش‌های شماست.",
  },
];

/** Results of one spreadsheet run: the file, its status, and a short table with the anomaly flagged. */
function SpreadsheetRun() {
  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex min-w-0 flex-col">
          <h3 className="text-h3 text-fg">تحلیل فایل اکسل</h3>
          <span dir="ltr" className="text-start text-caption text-fg-muted">
            {SHEET_FILE}
          </span>
        </div>
        <StatusBadge tone="success" icon={<CircleCheckIcon strokeWidth={1.75} aria-hidden />}>
          تحلیل شد
        </StatusBadge>
      </div>
      <table className="w-full text-small">
        <caption className="sr-only">نمونهٔ ردیف‌های تحلیل فایل فروش روزانه</caption>
        <thead className="bg-surface-sunken text-fg-muted">
          <tr>
            <th scope="col" className="px-4 py-2 text-start font-medium">
              محصول
            </th>
            <th scope="col" className="px-4 py-2 text-end font-medium">
              مبلغ (تومان)
            </th>
            <th scope="col" className="px-4 py-2 text-start font-medium max-sm:hidden">
              نتیجه
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {SHEET_ROWS.map((row) => (
            <tr key={row.product} className={cn(row.anomaly && "bg-warning-soft")}>
              <th scope="row" className="px-4 py-2 text-start font-medium text-fg">
                {row.product}
              </th>
              <td className="px-4 py-2 text-end text-fg">{row.amount}</td>
              <td className="px-4 py-2 max-sm:hidden">
                {row.anomaly ? (
                  <StatusBadge tone="warning" icon={<TriangleAlertIcon strokeWidth={1.75} aria-hidden />}>
                    هشدار: {row.note}
                  </StatusBadge>
                ) : (
                  <span className="text-fg-muted">عادی</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-border bg-warning-soft px-4 py-2 text-small text-warning-text sm:hidden">هشدار: فروش قهوه سه برابر معمول است.</p>
    </div>
  );
}

/** Reports and spreadsheets: real MetricStrip, BarChart and a run excerpt. Split opposite to the hero. */
export function ReportsSection() {
  return (
    <section id="reports" aria-labelledby="reports-title" className="scroll-mt-16 py-14 lg:py-20">
      <div className={`${CONTAINER} grid items-center gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14`}>
        <div className="min-w-0 overflow-hidden rounded-md border border-border-strong bg-page max-lg:order-last">
          <div className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3">
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-h3 text-fg">گزارش‌ها</span>
              <span className="text-caption text-fg-muted">{BUSINESS_NAME}، ۷ روز گذشته</span>
            </div>
          </div>
          <div className="flex flex-col gap-4 p-4">
            <MetricStrip items={REPORT_METRICS} label="شاخص‌های هفته" />
            <div className="rounded-md border border-border bg-surface p-4">
              <h3 className="mb-2 text-h3 text-fg">ثبت‌نام‌ها در هفتهٔ گذشته</h3>
              <BarChart points={REPORT_SERIES} label="ثبت‌نام‌های روزانه" unit="نفر" />
            </div>
            <SpreadsheetRun />
          </div>
        </div>

        <div className="flex flex-col gap-8">
          <h2 id="reports-title" className="text-h1 text-fg">
            گزارشی که مدیر می‌خواند
          </h2>
          <dl className="flex flex-col divide-y divide-border border-y border-border">
            {POINTS.map((p) => (
              <div key={p.title} className="flex flex-col gap-1 py-4">
                <dt className="text-h3 text-fg">{p.title}</dt>
                <dd className="text-body text-fg-secondary">{p.text}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}
