"use client";

import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface MetricColumn {
  key: string;
  label: string;
  numeric?: boolean;
  /** Shrink to the content (a rank or a percent) instead of sharing the row width. */
  narrow?: boolean;
  /** Custom cell content; the raw value is still what sorts. */
  render?: (value: unknown, row: Record<string, unknown>) => ReactNode;
}

const MAX_ROWS = 50;

function defaultCell(value: unknown, numeric: boolean): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="text-fg-muted">—</span>;
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "بله" : "خیر";
  if (typeof value === "string") return numeric ? value : <bdi>{value}</bdi>;
  return <bdi>{String(value)}</bdi>;
}

function compare(a: unknown, b: unknown, numeric: boolean): number {
  const aEmpty = a === null || a === undefined || a === "";
  const bEmpty = b === null || b === undefined || b === "";
  if (aEmpty || bEmpty) return aEmpty === bEmpty ? 0 : aEmpty ? 1 : -1;
  if (numeric) return Number(a) - Number(b);
  return String(a).localeCompare(String(b), "fa");
}

type Sort = { key: string; dir: "asc" | "desc" } | null;

/**
 * A ruled table with sortable columns: header buttons set `aria-sort`, numbers are tabular and end-aligned.
 * Scrolls sideways inside its own box on narrow screens; the page itself never scrolls sideways.
 */
export function MetricTable({
  columns,
  rows,
  label,
  initialSort = null,
}: {
  columns: MetricColumn[];
  rows: Record<string, unknown>[];
  /** Accessible name of the table. */
  label: string;
  initialSort?: Sort;
}) {
  const [sort, setSort] = useState<Sort>(initialSort);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => factor * compare(a[sort.key], b[sort.key], col?.numeric ?? false));
  }, [rows, columns, sort]);

  if (rows.length === 0 || columns.length === 0) return <p className="text-small text-fg-muted">داده‌ای برای نمایش نیست.</p>;
  const shown = sorted.slice(0, MAX_ROWS);

  function toggle(col: MetricColumn) {
    setSort((s) => (s?.key === col.key ? { key: col.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: col.key, dir: col.numeric ? "desc" : "asc" }));
  }

  return (
    <div className={cn("flex flex-col gap-2", columns.length <= 4 && "max-w-3xl")}>
      <div className="overflow-x-auto rounded-sm border border-border">
        <table aria-label={label} className="w-full text-small">
          <thead className="bg-surface-sunken">
            <tr>
              {columns.map((c) => {
                const state = sort?.key === c.key ? sort.dir : null;
                const Icon = state === "asc" ? ArrowUpIcon : state === "desc" ? ArrowDownIcon : ArrowUpDownIcon;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={state === "asc" ? "ascending" : state === "desc" ? "descending" : "none"}
                    className={cn("p-0 font-medium whitespace-nowrap text-fg-secondary", c.numeric ? "text-end" : "text-start", c.narrow && "w-px")}
                  >
                    <button
                      type="button"
                      onClick={() => toggle(c)}
                      className={cn(
                        "inline-flex min-h-10 w-full items-center gap-1.5 px-3 text-caption text-fg-secondary hover:text-fg",
                        c.numeric && "justify-end",
                      )}
                    >
                      {c.label}
                      <Icon aria-hidden strokeWidth={1.75} className={cn("size-3.5 shrink-0", !state && "text-fg-muted")} />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i} className="border-t border-border">
                {columns.map((c) => (
                  <td key={c.key} className={cn("px-3 py-2", c.numeric ? "text-end tabular-nums" : "text-start")}>
                    {c.render ? c.render(row[c.key], row) : defaultCell(row[c.key], !!c.numeric)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > shown.length && (
        <p className="text-caption text-fg-muted">فقط {formatNumber(shown.length)} ردیف اول از {formatNumber(rows.length)} نمایش داده شد.</p>
      )}
    </div>
  );
}
