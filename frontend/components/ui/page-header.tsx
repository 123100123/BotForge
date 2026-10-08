import * as React from "react";
import Link from "next/link";
import { ChevronRightIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Crumb {
  label: string;
  /** Omit on the current page (last crumb). */
  href?: string;
}

/**
 * Top of every page: optional breadcrumb, the page's only h1, a one-line description and an actions slot
 * (actions sit at the end edge; they wrap under the title on narrow screens).
 */
function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: Crumb[];
  className?: string;
}) {
  return (
    <header data-slot="page-header" className={cn("flex flex-col gap-2", className)}>
      {breadcrumb && breadcrumb.length > 0 && (
        <nav aria-label="مسیر صفحه">
          <ol className="flex flex-wrap items-center gap-1 text-small text-fg-muted">
            {breadcrumb.map((c, i) => (
              <li key={`${c.label}-${i}`} className="flex items-center gap-1">
                {i > 0 && <ChevronRightIcon className="size-3.5 rtl:-scale-x-100" aria-hidden />}
                {c.href ? (
                  <Link href={c.href} className="rounded-xs hover:text-fg hover:underline">
                    {c.label}
                  </Link>
                ) : (
                  <span aria-current="page">{c.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-72 flex-col gap-1">
          <h1 className="text-h1 text-fg">{title}</h1>
          {description && <p className="max-w-prose text-body text-fg-secondary">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export { PageHeader };
