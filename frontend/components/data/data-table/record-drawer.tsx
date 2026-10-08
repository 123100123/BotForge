"use client";

import type { ReactNode } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

/**
 * Detail drawer: a sheet from the end edge, a bottom sheet below 640px. `title` is always present (the
 * accessible name); `description` is the one-line subtitle.
 */
export function RecordDrawer({
  open,
  onOpenChange,
  title,
  description,
  badge,
  wide,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  /** Status badge shown beside the title. */
  badge?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  const mobile = useMediaQuery("(max-width: 639.98px)");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={mobile ? "bottom" : "end"}
        className={cn(!mobile && (wide ? "w-[min(100%-2rem,34rem)]" : "w-[min(100%-2rem,30rem)]"), mobile && "max-h-[90dvh] p-4 pb-6")}
      >
        <SheetHeader>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <SheetTitle>{title}</SheetTitle>
            {badge}
          </div>
          {description ? (
            <SheetDescription asChild>
              <div>{description}</div>
            </SheetDescription>
          ) : (
            <SheetDescription className="sr-only">جزئیات</SheetDescription>
          )}
        </SheetHeader>
        {children}
      </SheetContent>
    </Sheet>
  );
}

/** A titled block inside a drawer: h3 heading, then content. Sections are separated by a divider. */
export function DrawerSection({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("flex flex-col gap-3 border-t border-border pt-4", className)}>
      {title && <h3 className="text-h3 text-fg">{title}</h3>}
      {children}
    </section>
  );
}

/** Label/value rows of a drawer. */
export function DetailList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-x-4 gap-y-2 text-small">
      {items.map((it) => (
        <div key={it.label} className="contents">
          <dt className="text-fg-muted">{it.label}</dt>
          <dd className="min-w-0 text-fg">{it.value}</dd>
        </div>
      ))}
    </dl>
  );
}
