import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function PageHeader({ eyebrow, title, description, action, className, level = 2 }: { eyebrow?: string; title: string; description?: string; action?: ReactNode; className?: string; level?: 1 | 2 }) {
  const Heading = level === 1 ? "h1" : "h2";
  return (
    <header className={cn("flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 space-y-2">
        {eyebrow && <p className="app-section-label">{eyebrow}</p>}
        <Heading className="text-3xl font-extrabold tracking-tight text-foreground md:text-4xl">{title}</Heading>
        {description && <p className="max-w-2xl text-sm leading-7 text-muted-foreground md:text-base">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </header>
  );
}

export function SectionToolbar({ title, description, actions, className }: { title: string; description?: string; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between", className)}>
      <div><h2 className="text-lg font-bold text-foreground">{title}</h2>{description && <p className="text-sm text-muted-foreground">{description}</p>}</div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function MetricCard({ label, value, detail, icon, tone = "default", className }: { label: string; value: ReactNode; detail?: string; icon?: ReactNode; tone?: "default" | "accent" | "teal"; className?: string }) {
  return (
    <Card className={cn("min-w-0 rounded-2xl border border-border p-5", className)}>
      <div className="flex items-start justify-between gap-3 text-sm text-muted-foreground">
        <span>{label}</span>
        {icon && <span className={tone === "teal" ? "text-teal" : tone === "accent" ? "text-primary" : "text-muted-foreground"}>{icon}</span>}
      </div>
      <strong className="mt-4 block text-3xl font-extrabold tabular-nums text-foreground">{value}</strong>
      {detail && <p className="mt-2 text-xs text-muted-foreground">{detail}</p>}
    </Card>
  );
}

export function StatusChip({ children, tone = "secondary" }: { children: ReactNode; tone?: "secondary" | "success" | "warning" | "destructive" | "accent" }) {
  return <Badge variant={tone}>{children}</Badge>;
}

export function EmptyState({ icon, title, description, action, className }: { icon?: ReactNode; title: string; description?: string; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("app-subtle-surface flex flex-col items-center px-6 py-12 text-center", className)}>
      {icon && <span className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-card text-primary">{icon}</span>}
      <h3 className="text-lg font-bold text-foreground">{title}</h3>
      {description && <p className="mt-2 max-w-md text-sm leading-7 text-muted-foreground">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
