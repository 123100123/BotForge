import { Minus, Pencil, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SpecChange } from "@/lib/types";

const ICONS: Record<SpecChange["kind"], typeof Plus> = { added: Plus, removed: Minus, changed: Pencil };
const STYLES: Record<SpecChange["kind"], string> = {
  added: "bg-success-soft",
  removed: "bg-danger-soft",
  changed: "bg-warning-soft",
};
const ICON_STYLES: Record<SpecChange["kind"], string> = {
  added: "text-success-text",
  removed: "text-danger-text",
  changed: "text-warning-text",
};
const KIND_LABELS: Record<SpecChange["kind"], string> = { added: "افزوده شد", removed: "حذف شد", changed: "تغییر کرد" };

/** Splits "prefix label: old ← new" so the old value can be struck through. Null when the label has no such shape. */
function splitChange(label: string): { head: string; oldValue: string; newValue: string } | null {
  const arrow = label.lastIndexOf(" ← ");
  if (arrow === -1) return null;
  const before = label.slice(0, arrow);
  const newValue = label.slice(arrow + 3);
  const colon = before.lastIndexOf(": ");
  if (colon === -1) return null;
  return { head: before.slice(0, colon), oldValue: before.slice(colon + 2), newValue };
}

/** The `diff` lines of a revision against its parent, with the backend's Persian labels. */
export function SpecDiff({ diff, isFirst, emptyText }: { diff: SpecChange[]; isFirst: boolean; emptyText?: string }) {
  if (diff.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border-strong p-4 text-small text-fg-muted">
        {emptyText ??
          (isFirst ? "این اولین نسخهٔ ربات است و نسخهٔ قبلی برای مقایسه وجود ندارد." : "این نسخه نسبت به نسخهٔ قبل تغییری در پیکربندی ندارد.")}
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-2" aria-label="تغییرات پیکربندی">
      {diff.map((c, i) => {
        const Icon = ICONS[c.kind];
        const parts = c.kind === "changed" ? splitChange(c.label_fa) : null;
        return (
          <li key={i} className={cn("flex items-start gap-2.5 rounded-sm px-3 py-2 text-body", STYLES[c.kind])}>
            <Icon strokeWidth={1.75} className={cn("mt-2 size-4 shrink-0", ICON_STYLES[c.kind])} aria-label={KIND_LABELS[c.kind]} />
            {parts ? (
              <span className="min-w-0">
                {parts.head}: <del className="text-fg-muted">{parts.oldValue}</del>{" "}
                <span aria-hidden className="inline-block text-fg-muted rtl:-scale-x-100">
                  →
                </span>{" "}
                <ins className="font-medium no-underline">{parts.newValue}</ins>
              </span>
            ) : (
              <span className="min-w-0">{c.label_fa}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
