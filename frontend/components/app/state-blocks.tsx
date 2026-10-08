import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Inbox, LoaderCircle } from "lucide-react";
import { Skeleton } from "@heroui/react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
export function ErrorNote({ children, className }: { children: ReactNode; className?: string }) {
  return <div role="alert" className={cn("flex min-w-0 items-start gap-3 rounded-2xl border border-destructive/15 bg-destructive/8 p-4 text-sm leading-7 text-destructive", className)}><AlertCircle className="mt-1 size-4 shrink-0" aria-hidden /><div className="min-w-0 break-words">{children}</div></div>;
}
export function InfoNote({ children, tone = "success", className }: { children: ReactNode; tone?: "success" | "warning"; className?: string }) {
  return <div role="status" className={cn("flex min-w-0 items-start gap-3 rounded-2xl border p-4 text-sm leading-7", tone === "success" ? "border-success/15 bg-success/8 text-success" : "border-warning/15 bg-warning/8 text-warning", className)}><CheckCircle2 className="mt-1 size-4 shrink-0" aria-hidden /><div className="min-w-0 break-words">{children}</div></div>;
}
export function LoadingBlock({ className }: { className?: string }) {
  return <div role="status" aria-label="در حال بارگذاری" className={cn("space-y-5", className)}><div className="flex items-center gap-2 text-xs text-muted-foreground"><LoaderCircle className="size-4 animate-spin" />در حال آماده‌سازی…</div><Skeleton className="h-8 w-48 rounded-xl" /><div className="grid gap-4 sm:grid-cols-2"><Skeleton className="h-40 rounded-2xl" /><Skeleton className="h-40 rounded-2xl" /></div></div>;
}
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <Card className="flex flex-col items-center gap-4 rounded-3xl border border-dashed px-5 py-12 text-center"><span className="grid size-14 place-items-center rounded-2xl bg-primary/8 text-primary"><Inbox className="size-6" aria-hidden /></span><h3 className="text-lg font-bold">{title}</h3>{children && <div className="max-w-md text-sm leading-7 text-muted-foreground">{children}</div>}{action && <div className="mt-1 flex flex-wrap justify-center gap-2">{action}</div>}</Card>;
}
