import { Minus, Pencil, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SpecChange } from "@/lib/types";

const ICONS: Record<SpecChange["kind"], typeof Plus> = { added: Plus, removed: Minus, changed: Pencil };
const STYLES: Record<SpecChange["kind"], string> = {
  added: "border-success/30 bg-success/10",
  removed: "border-destructive/30 bg-destructive/10",
  changed: "border-warning/30 bg-warning/15",
};
const ICON_STYLES: Record<SpecChange["kind"], string> = {
  added: "text-success",
  removed: "text-destructive",
  changed: "text-warning",
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
export function SpecDiff({ diff, isFirst }: { diff: SpecChange[]; isFirst: boolean }) {
  if (diff.length === 0) {
    return (
      <p className="rounded-lg border border-dashed p-4 text-sm leading-7 text-muted-foreground">
        {isFirst ? "این اولین نسخهٔ ربات است و نسخهٔ قبلی برای مقایسه وجود ندارد." : "این نسخه نسبت به نسخهٔ قبل تغییری در مشخصات ندارد."}
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-2.5" aria-label="تغییرات نسبت به نسخهٔ قبل">
      {diff.map((c, i) => {
        const Icon = ICONS[c.kind];
        const parts = c.kind === "changed" ? splitChange(c.label_fa) : null;
        return (
          <li key={i} className={cn("flex items-start gap-3 rounded-xl border px-4 py-3 text-sm leading-7", STYLES[c.kind])}>
            <Icon className={cn("mt-1.5 size-4 shrink-0", ICON_STYLES[c.kind])} aria-label={KIND_LABELS[c.kind]} />
            {parts ? (
              <span>
                {parts.head}: <del className="text-muted-foreground">{parts.oldValue}</del> ← <ins className="font-medium no-underline">{parts.newValue}</ins>
              </span>
            ) : (
              <span>{c.label_fa}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
