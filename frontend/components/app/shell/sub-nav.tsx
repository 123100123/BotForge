"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

export interface SubNavItem {
  href: string;
  label: string;
}

/**
 * Underline tabs between the sub-pages of a section (Changes, Reports, Settings). Links, not tab state:
 * each sub-page has its own URL. The active item is the longest href that prefixes the path.
 */
export function SubNav({ label, items, className }: { label: string; items: SubNavItem[]; className?: string }) {
  const pathname = usePathname().replace(/\/+$/, "");
  const active = items
    .filter((i) => pathname === i.href || pathname.startsWith(`${i.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0];

  return (
    <nav aria-label={label} className={cn("-mt-2", className)}>
      <ul className="flex w-full items-center gap-1 overflow-x-auto border-b border-border">
        {items.map((item) => {
          const current = item === active;
          return (
            <li key={item.href} className="shrink-0">
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "-mb-px inline-flex min-h-11 items-center border-b-2 border-transparent px-4 text-small font-medium whitespace-nowrap text-fg-muted transition-colors duration-fast hover:text-fg",
                  current && "border-brand text-fg",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
