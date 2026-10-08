"use client";

import { usePathname } from "next/navigation";
import { useBusiness } from "@/components/app/business-context";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { BusinessSwitcher } from "./business-switcher";
import { NavGroupList, useNavBadges } from "./nav-list";

/**
 * The full navigation: business switcher, then the groups (نمای کلی · عملیات · تحلیل · ساخت), with
 * تنظیمات pinned to the bottom. Used by the desktop sidebar and by the tablet rail's expanded sheet.
 */
export function SidebarNav({
  onNavigate,
  large,
  inSheet,
}: {
  onNavigate?: () => void;
  large?: boolean;
  /** Rendered in a sheet: leave room for the sheet's close button at the end edge. */
  inSheet?: boolean;
}) {
  const { nav, dataStatus } = useBusiness();
  const pathname = usePathname();
  const badges = useNavBadges();
  const main = nav.filter((g) => g.id !== "settings");
  const settings = nav.find((g) => g.id === "settings");

  return (
    <nav aria-label="بخش‌های کسب‌وکار" className="flex min-h-0 flex-1 flex-col">
      <div className={cn("border-b p-3", inSheet && "pe-12")}>
        <BusinessSwitcher onNavigate={onNavigate} />
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-3">
        {main.map((group) => (
          <NavGroupList key={group.id} group={group} pathname={pathname} badges={badges} onNavigate={onNavigate} large={large} />
        ))}
        {dataStatus === "loading" && (
          <div className="flex flex-col gap-2 px-3" role="status" aria-label="در حال بارگذاری بخش‌های عملیات">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-7 w-32" />
            <Skeleton className="h-7 w-28" />
          </div>
        )}
      </div>
      {settings && (
        <div className="border-t p-3">
          <NavGroupList group={settings} pathname={pathname} badges={badges} onNavigate={onNavigate} large={large} />
        </div>
      )}
    </nav>
  );
}

/** ≥1024px: full-height sidebar on the start edge (right in RTL), 248px, sticky, with its own scroll. */
export function AppSidebar() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-[248px] shrink-0 flex-col border-e bg-surface lg:flex">
      <SidebarNav />
    </aside>
  );
}
