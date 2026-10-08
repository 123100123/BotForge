"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { cn } from "@/lib/utils";

/**
 * One settings section: a single bordered panel (radius 12, no shadow) with an h2 title, an optional
 * status at the end edge, and body sections separated by dividers. Never nest panels or cards inside it.
 */
export function SettingsPanel({
  title,
  description,
  status,
  children,
  className,
}: {
  title: string;
  description?: ReactNode;
  /** A StatusBadge (or similar) shown at the end of the header. */
  status?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className={cn("rounded-md border border-border bg-surface text-fg", className)}>
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 p-5">
        <div className="flex min-w-0 flex-1 basis-60 flex-col gap-1">
          <h2 id={titleId} className="text-h3 text-fg">
            {title}
          </h2>
          {description && <p className="max-w-prose text-small text-fg-secondary">{description}</p>}
        </div>
        {status && <div className="shrink-0">{status}</div>}
      </header>
      <div className="flex flex-col">{children}</div>
    </section>
  );
}

/** A divided block inside a panel. `tone="danger"` marks the destructive zone (kept apart from primary actions). */
export function PanelSection({
  title,
  description,
  tone,
  children,
  className,
}: {
  title?: string;
  description?: ReactNode;
  tone?: "danger";
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-3 border-t border-border p-5", className)}>
      {(title || description) && (
        <div className="flex flex-col gap-1">
          {title && <h3 className={cn("text-body font-semibold", tone === "danger" ? "text-danger-text" : "text-fg")}>{title}</h3>}
          {description && <p className="max-w-prose text-small text-fg-secondary">{description}</p>}
        </div>
      )}
      {children}
    </div>
  );
}

/** Label and value on one line (stacked on narrow screens). Wrap several in a <dl>. */
export function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-6">
      <dt className="shrink-0 text-small text-fg-muted sm:w-36">{label}</dt>
      <dd className="min-w-0 text-body text-fg">{children}</dd>
    </div>
  );
}

/** A link or code shown left-to-right in a sunken box. */
export function LinkBox({ value }: { value: string }) {
  return (
    <div
      dir="ltr"
      className="min-w-0 rounded-sm border border-border bg-surface-sunken px-3 py-2 text-start text-small break-all text-fg"
    >
      {value}
    </div>
  );
}

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Copies `value` and answers with a toast (success, or a hint to copy by hand when the browser refuses). */
async function copyWithToast(value: string): Promise<boolean> {
  const ok = await writeClipboard(value);
  if (ok) toast({ title: "پیوند کپی شد", tone: "success", duration: 2500 });
  else toast({ title: "کپی خودکار انجام نشد", description: "پیوند را دستی انتخاب و کپی کنید.", tone: "danger" });
  return ok;
}

export function CopyButton({ value, label = "کپی پیوند", variant = "secondary" }: { value: string; label?: string; variant?: "secondary" | "primary" }) {
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  async function copy() {
    const ok = await copyWithToast(value);
    setDone(ok);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setDone(false), 2000);
  }
  return (
    <Button variant={variant} onClick={() => void copy()}>
      {done ? <Check strokeWidth={1.75} /> : <Copy strokeWidth={1.75} />}
      {done ? "کپی شد" : label}
    </Button>
  );
}

/** Outlined danger action (not a solid fill): disconnect, revoke. Sits in its own PanelSection. */
export const DANGER_OUTLINE = "border-danger text-danger-text hover:bg-danger-soft";
