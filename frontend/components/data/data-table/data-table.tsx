"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown, EllipsisVertical, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import { FilterTabs, type FilterTabOption } from "./filter-tabs";

export interface RowAction {
  key: string;
  label: string;
  icon?: ReactNode;
  /** Destructive actions are drawn in the danger tone (the caller asks for confirmation). */
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export interface DataColumn<T> {
  id: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Makes the column sortable. Numbers compare by value, strings in Persian collation; empty sorts last. */
  sortValue?: (row: T) => string | number | null;
  align?: "start" | "end";
  /** Width classes (`w-32`). A column without one shares what is left; it is the one that truncates. */
  className?: string;
  /** Lower-priority columns disappear below this breakpoint (768 or 1024). */
  hideBelow?: "md" | "lg";
}

export interface StatusFilterConfig<T> {
  options: { key: string; label: string }[];
  get: (row: T) => string | null;
  /** Status selected at first (for example from `?status=`). Ignored when it is not one of the options. */
  initial?: string | null;
}

export interface DataTableProps<T> {
  /** Accessible name of the table. */
  label: string;
  /** null while loading. */
  rows: T[] | null;
  rowKey: (row: T) => string | number;
  columns: DataColumn<T>[];
  error?: string | null;
  onRetry?: () => void;
  /** Enables the search box; return everything a person may type to find the row. */
  searchText?: (row: T) => string;
  searchPlaceholder?: string;
  /** Enables the status tabs with counts over the loaded rows. */
  statusFilter?: StatusFilterConfig<T>;
  /** Extra controls at the end of the toolbar. */
  toolbarEnd?: ReactNode;
  onRowOpen?: (row: T) => void;
  selectedKey?: string | number | null;
  rowActions?: (row: T) => RowAction[];
  /**
   * Width of the actions column from 1024px up, where up to two actions sit in the row as buttons:
   * sm 176px, md 224px (default), lg 256px. Below 1024px every row shows the «اقدام‌ها» menu instead.
   */
  actionsWidth?: keyof typeof ACTIONS_WIDTH;
  /** Below 640px a row becomes a list entry: a title, a line of key fields and the status. */
  mobile: { title: (row: T) => ReactNode; meta?: (row: T) => ReactNode; status?: (row: T) => ReactNode };
  /** Total on the server, and paging of the loaded part. */
  total?: number;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
  /** Shown when there are no rows at all (not when a filter hides them). */
  empty: { icon?: ReactNode; title: string; description?: ReactNode; action?: ReactNode };
  defaultSort?: { id: string; dir: "asc" | "desc" };
  className?: string;
}

const ACTIONS_WIDTH = { sm: "w-14 lg:w-44", md: "w-14 lg:w-56", lg: "w-14 lg:w-64" } as const;

const HIDE: Record<NonNullable<DataColumn<unknown>["hideBelow"]>, string> = {
  md: "max-md:hidden",
  lg: "max-lg:hidden",
};

const FA_TO_ASCII: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((c, i) => (FA_TO_ASCII[c] = String(i)));
"٠١٢٣٤٥٦٧٨٩".split("").forEach((c, i) => (FA_TO_ASCII[c] = String(i)));

/** Case, digit-script and Arabic/Persian letter variants should not stop a search from matching. */
export function normalizeSearch(text: string): string {
  return text
    .replace(/[۰-۹٠-٩]/g, (d) => FA_TO_ASCII[d] ?? d)
    .replace(/ي/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[‌‏‎]/g, " ")
    .replace(/\s+/g, " ")
    .toLowerCase()
    .trim();
}

function compare(a: string | number | null, b: string | number | null, dir: "asc" | "desc"): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1; // empty values sort last in both directions
  if (b === null) return -1;
  const r = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), "fa");
  return dir === "asc" ? r : -r;
}

/**
 * The data table every Operations view uses: sticky header, search over the loaded rows, status tabs with
 * counts, sortable columns, a row that opens a drawer, and row actions. Below 640px it renders a list.
 * It holds only view state (query, filter, sort); the rows, paging and the drawer belong to the caller.
 */
export function DataTable<T>({
  label,
  rows,
  rowKey,
  columns,
  error,
  onRetry,
  searchText,
  searchPlaceholder = "جستجو",
  statusFilter,
  toolbarEnd,
  onRowOpen,
  selectedKey,
  rowActions,
  actionsWidth = "md",
  mobile,
  total,
  hasMore,
  loadingMore,
  onLoadMore,
  empty,
  defaultSort,
  className,
}: DataTableProps<T>) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ id: string; dir: "asc" | "desc" } | null>(defaultSort ?? null);
  const initialStatus =
    statusFilter?.initial && statusFilter.options.some((o) => o.key === statusFilter.initial) ? statusFilter.initial : null;
  const [status, setStatus] = useState<string | null>(initialStatus);

  const counts = useMemo(() => {
    const c = new Map<string, number>();
    if (rows && statusFilter) {
      for (const r of rows) {
        const s = statusFilter.get(r);
        if (s) c.set(s, (c.get(s) ?? 0) + 1);
      }
    }
    return c;
  }, [rows, statusFilter]);

  const visible = useMemo(() => {
    if (!rows) return [];
    let list = rows;
    if (statusFilter && status) list = list.filter((r) => statusFilter.get(r) === status);
    const q = normalizeSearch(query);
    if (q && searchText) list = list.filter((r) => normalizeSearch(searchText(r)).includes(q));
    const col = sort ? columns.find((c) => c.id === sort.id) : undefined;
    if (col?.sortValue && sort) {
      const get = col.sortValue;
      list = [...list].sort((a, b) => compare(get(a), get(b), sort.dir));
    }
    return list;
  }, [rows, statusFilter, status, query, searchText, sort, columns]);

  if (error && !rows) return <ErrorState message={error} onRetry={onRetry} />;
  if (rows === null) return <TableSkeleton columns={columns} label={label} />;
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-border bg-surface">
        <EmptyState icon={empty.icon} title={empty.title} description={empty.description} action={empty.action} />
      </div>
    );
  }

  const tabs: FilterTabOption[] | null = statusFilter
    ? [
        { key: null, label: "همه", count: rows.length },
        ...statusFilter.options.map((o) => ({ key: o.key, label: o.label, count: counts.get(o.key) ?? 0 })),
      ]
    : null;
  const filtered = status !== null || query.trim() !== "";
  const actionsFor = rowActions;

  function toggleSort(id: string) {
    setSort((s) => (s?.id !== id ? { id, dir: "asc" } : s.dir === "asc" ? { id, dir: "desc" } : null));
  }

  function clearFilters() {
    setQuery("");
    setStatus(null);
  }

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {tabs && <FilterTabs options={tabs} value={status} onChange={setStatus} label="فیلتر بر اساس وضعیت" />}
      {(searchText || toolbarEnd) && (
        <div className="flex flex-wrap items-center gap-2">
          {searchText && (
            <div className="relative min-w-0 flex-1 sm:max-w-xs sm:flex-none sm:basis-72">
              <Search aria-hidden className="pointer-events-none absolute inset-y-0 start-3 my-auto size-4 text-fg-muted" strokeWidth={1.75} />
              <Input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={searchPlaceholder}
                aria-label={searchPlaceholder}
                className="ps-9"
              />
            </div>
          )}
          {toolbarEnd}
        </div>
      )}

      {visible.length === 0 ? (
        <div className="rounded-md border border-border bg-surface">
          <EmptyState
            icon={<Search />}
            title="نتیجه‌ای پیدا نشد"
            description="فیلتر یا عبارت جستجو را تغییر دهید."
            action={
              filtered ? (
                <Button variant="secondary" size="sm" onClick={clearFilters}>
                  پاک کردن فیلترها
                </Button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <>
          {/* ≥640px: a table. The header sticks below the 56px top bar. */}
          <div className="max-sm:hidden rounded-md border border-border bg-surface">
            <table aria-label={label} className="w-full table-fixed border-separate border-spacing-0">
              <thead>
                <tr>
                  {columns.map((c) => {
                    const sorted = sort?.id === c.id ? sort.dir : null;
                    return (
                      <th
                        key={c.id}
                        scope="col"
                        aria-sort={c.sortValue ? (sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none") : undefined}
                        className={cn(
                          "sticky top-14 z-sticky border-b border-border bg-surface-sunken px-3 py-2 text-caption font-medium text-fg-secondary first:rounded-ss-md last:rounded-se-md",
                          c.align === "end" ? "text-end" : "text-start",
                          c.className,
                          c.hideBelow && HIDE[c.hideBelow],
                        )}
                      >
                        {c.sortValue ? (
                          <button
                            type="button"
                            onClick={() => toggleSort(c.id)}
                            className={cn(
                              "-mx-1 inline-flex items-center gap-1 rounded-xs px-1 hover:text-fg",
                              c.align === "end" && "flex-row-reverse",
                              sorted && "text-fg",
                            )}
                          >
                            {c.header}
                            {sorted === "asc" ? (
                              <ArrowUp aria-hidden className="size-3.5" strokeWidth={1.75} />
                            ) : sorted === "desc" ? (
                              <ArrowDown aria-hidden className="size-3.5" strokeWidth={1.75} />
                            ) : (
                              <ChevronsUpDown aria-hidden className="size-3.5 text-fg-muted" strokeWidth={1.75} />
                            )}
                          </button>
                        ) : (
                          c.header
                        )}
                      </th>
                    );
                  })}
                  {actionsFor && (
                    <th scope="col" className={cn("sticky top-14 z-sticky border-b border-border bg-surface-sunken px-3 py-2 last:rounded-se-md", ACTIONS_WIDTH[actionsWidth])}>
                      <span className="sr-only">اقدام‌ها</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="[&>tr:last-child>td]:border-b-0">
                {visible.map((row) => {
                  const key = rowKey(row);
                  const selected = selectedKey !== undefined && selectedKey !== null && selectedKey === key;
                  return (
                    <tr
                      key={key}
                      onClick={onRowOpen ? () => onRowOpen(row) : undefined}
                      className={cn(onRowOpen && "cursor-pointer", selected ? "bg-brand-soft" : "hover:bg-surface-sunken")}
                    >
                      {columns.map((c, i) => (
                        <td
                          key={c.id}
                          className={cn(
                            "overflow-hidden border-b border-border px-3 py-2 align-middle text-small text-fg",
                            c.align === "end" ? "text-end" : "text-start",
                            c.hideBelow && HIDE[c.hideBelow],
                          )}
                        >
                          {i === 0 && onRowOpen ? (
                            <button type="button" className="block w-full min-w-0 rounded-xs text-start font-medium hover:underline">
                              {c.cell(row)}
                            </button>
                          ) : (
                            c.cell(row)
                          )}
                        </td>
                      ))}
                      {actionsFor && (
                        <td className="border-b border-border px-3 py-1 align-middle" onClick={(e) => e.stopPropagation()}>
                          <RowActions actions={actionsFor(row)} />
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* <640px: a list. */}
          <ul aria-label={label} className="sm:hidden rounded-md border border-border bg-surface">
            {visible.map((row) => {
              const key = rowKey(row);
              const actions = actionsFor ? actionsFor(row) : [];
              return (
                <li key={key} className="flex items-start gap-1 border-b border-border p-3 last:border-b-0">
                  <button
                    type="button"
                    disabled={!onRowOpen}
                    onClick={() => onRowOpen?.(row)}
                    className="flex min-w-0 flex-1 flex-col items-start gap-1 rounded-xs text-start"
                  >
                    <span className="block w-full truncate text-body font-medium text-fg">{mobile.title(row)}</span>
                    {mobile.meta && <span className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 text-small text-fg-secondary">{mobile.meta(row)}</span>}
                    {mobile.status && <span className="mt-0.5">{mobile.status(row)}</span>}
                  </button>
                  {actions.length > 0 && <RowActionsMenu actions={actions} />}
                </li>
              );
            })}
          </ul>
        </>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 text-small text-fg-muted">
        <span role="status">
          {filtered ? `${fa(visible.length)} نتیجه از ${fa(rows.length)} مورد بارگذاری‌شده` : `${fa(rows.length)} مورد${total !== undefined && total > rows.length ? ` از ${fa(total)}` : ""}`}
          {hasMore && statusFilter ? " · شمارندهٔ وضعیت‌ها فقط موارد بارگذاری‌شده را می‌شمارد" : ""}
        </span>
        {hasMore && onLoadMore && (
          <Button variant="secondary" size="sm" loading={loadingMore} onClick={onLoadMore}>
            بارگذاری بیشتر
          </Button>
        )}
      </div>
      {error && <p role="alert" className="text-small text-danger-text">{error}</p>}
    </div>
  );
}

/** Up to two actions sit in the row; more collapse into the menu. */
function RowActions({ actions }: { actions: RowAction[] }) {
  if (actions.length === 0) return null;
  if (actions.length > 2) {
    return (
      <div className="flex justify-end">
        <RowActionsMenu actions={actions} />
      </div>
    );
  }
  return (
    <>
      <div className="flex justify-end lg:hidden">
        <RowActionsMenu actions={actions} />
      </div>
      <div className="flex flex-nowrap items-center justify-end gap-1 max-lg:hidden">
        {actions.map((a) => (
          <Button
            key={a.key}
            variant={a.danger ? "ghost" : "secondary"}
            size="sm"
            className={cn("min-w-12", a.danger && "text-danger-text hover:text-danger-text")}
            disabled={a.disabled}
            onClick={a.onSelect}
          >
            {a.icon}
            {a.label}
          </Button>
        ))}
      </div>
    </>
  );
}

/** The «اقدام‌ها» menu of a row, for views that draw their own rows. */
export function RowActionsMenu({ actions }: { actions: RowAction[] }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="اقدام‌ها" className="max-sm:size-11">
          <EllipsisVertical aria-hidden strokeWidth={1.75} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {actions.map((a) => (
          <DropdownMenuItem key={a.key} variant={a.danger ? "danger" : undefined} disabled={a.disabled} onSelect={a.onSelect}>
            {a.icon}
            {a.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function TableSkeleton<T>({ columns, label }: { columns: DataColumn<T>[]; label: string }) {
  return (
    <div role="status" aria-label={`در حال بارگذاری ${label}`} className="flex flex-col gap-3">
      <Skeleton className="h-10 w-full max-w-md" />
      <div className="rounded-md border border-border bg-surface">
        <div className="h-9 rounded-t-md bg-surface-sunken" />
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex h-10 items-center gap-6 border-t border-border px-3">
            {columns.slice(0, 4).map((c, j) => (
              <Skeleton key={c.id} className={cn("h-3.5", j === 0 ? "w-40" : "w-20", j > 1 && "max-sm:hidden")} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
