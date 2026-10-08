"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { ChartColumn, Ellipsis, LayoutDashboard, LayoutList, LogOut, MessageCircleQuestion } from "lucide-react";
import { useSignOut } from "@/components/app/account-menu";
import { useBusiness } from "@/components/app/business-context";
import { ThemeChoice } from "@/components/app/theme-choice";
import { useAssistant } from "@/components/copilot/assistant-provider";
import { EmptyState } from "@/components/ui/empty-state";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { isNavItemActive, type NavGroup } from "@/lib/nav";
import { sectionHref } from "@/lib/routes";
import { cn } from "@/lib/utils";
import { BusinessSwitcher } from "./business-switcher";
import { NavCount, NavGroupList, useNavBadges } from "./nav-list";

const TAB_CLASS =
  "relative flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-caption font-medium text-fg-muted transition-colors duration-fast hover:text-fg";
const TAB_ACTIVE_CLASS = "text-brand-text";

function groupActive(groups: (NavGroup | undefined)[], pathname: string): boolean {
  return groups.some((g) => g && [...g.items, ...g.overflow].some((i) => isNavItemActive(i, pathname)));
}

function TabIcon({ children, active }: { children: ReactNode; active: boolean }) {
  return (
    <span className={cn("flex h-7 w-12 items-center justify-center rounded-sm", active && "bg-brand-soft")}>{children}</span>
  );
}

/**
 * <640px: the fixed bottom tab bar, exactly five items (D30): نمای کلی · عملیات (sheet) · دستیار ·
 * گزارش‌ها · بیشتر (sheet: build items, settings, business switcher, theme, sign out).
 */
export function MobileTabBar() {
  const { bot, nav } = useBusiness();
  const pathname = usePathname();
  const assistant = useAssistant();
  const badges = useNavBadges();
  const signOut = useSignOut();
  const [sheet, setSheet] = useState<"operations" | "more" | null>(null);
  const close = () => setSheet(null);

  const overview = nav.find((g) => g.id === "overview");
  const operations = nav.find((g) => g.id === "operations");
  const insights = nav.find((g) => g.id === "insights");
  const build = nav.find((g) => g.id === "build");
  const settings = nav.find((g) => g.id === "settings");
  // «بیشتر» lists insights beyond Reports (spreadsheets), the build group and settings.
  const extraInsights: NavGroup | undefined = insights && { ...insights, items: insights.items.filter((i) => i.id !== "reports") };

  const reportsHref = sectionHref(bot.id, "reports");
  const overviewActive = groupActive([overview], pathname);
  const reportsActive = pathname.startsWith(reportsHref);
  const operationsActive = groupActive([operations], pathname);
  const moreActive = groupActive([extraInsights, build, settings], pathname);
  const moreBadge = build ? build.items.map((i) => badges[i.id]).find(Boolean) : undefined;

  return (
    <>
      <nav
        aria-label="بخش‌های اصلی"
        className="fixed inset-x-0 bottom-0 z-sticky border-t bg-surface pb-[env(safe-area-inset-bottom)] sm:hidden"
      >
        <ul className="flex items-stretch">
          <li className="flex flex-1">
            <Link href={sectionHref(bot.id, "overview")} aria-current={overviewActive ? "page" : undefined} className={cn(TAB_CLASS, overviewActive && TAB_ACTIVE_CLASS)}>
              <TabIcon active={overviewActive}>
                <LayoutDashboard className="size-5" strokeWidth={1.75} aria-hidden />
              </TabIcon>
              نمای کلی
            </Link>
          </li>
          <li className="flex flex-1">
            <button
              type="button"
              onClick={() => setSheet("operations")}
              aria-haspopup="dialog"
              className={cn(TAB_CLASS, operationsActive && TAB_ACTIVE_CLASS)}
            >
              <TabIcon active={operationsActive}>
                <LayoutList className="size-5" strokeWidth={1.75} aria-hidden />
              </TabIcon>
              عملیات
            </button>
          </li>
          <li className="flex flex-1">
            <button type="button" onClick={() => assistant.open()} aria-haspopup="dialog" className={cn(TAB_CLASS, assistant.isOpen && TAB_ACTIVE_CLASS)}>
              <TabIcon active={assistant.isOpen}>
                <MessageCircleQuestion className="size-5" strokeWidth={1.75} aria-hidden />
              </TabIcon>
              دستیار
            </button>
          </li>
          <li className="flex flex-1">
            <Link href={reportsHref} aria-current={reportsActive ? "page" : undefined} className={cn(TAB_CLASS, reportsActive && TAB_ACTIVE_CLASS)}>
              <TabIcon active={reportsActive}>
                <ChartColumn className="size-5" strokeWidth={1.75} aria-hidden />
              </TabIcon>
              گزارش‌ها
            </Link>
          </li>
          <li className="flex flex-1">
            <button type="button" onClick={() => setSheet("more")} aria-haspopup="dialog" className={cn(TAB_CLASS, moreActive && TAB_ACTIVE_CLASS)}>
              <TabIcon active={moreActive}>
                <Ellipsis className="size-5" strokeWidth={1.75} aria-hidden />
              </TabIcon>
              بیشتر
              {moreBadge && <NavCount badge={moreBadge} className="absolute end-[calc(50%-1.75rem)] top-1.5 ms-0" />}
            </button>
          </li>
        </ul>
      </nav>

      <Sheet open={sheet === "operations"} onOpenChange={(o) => !o && close()}>
        <SheetContent side="bottom" className="gap-3 px-4 pt-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
          <SheetHeader>
            <SheetTitle>عملیات</SheetTitle>
            <SheetDescription className="sr-only">کارهای روزانهٔ کسب‌وکار</SheetDescription>
          </SheetHeader>
          {operations && (operations.items.length > 0 || operations.overflow.length > 0) ? (
            <NavGroupList group={operations} pathname={pathname} badges={badges} onNavigate={close} large showLabel={false} />
          ) : (
            <EmptyState
              as="h3"
              title="هنوز بخشی برای عملیات نیست"
              description="وقتی قابلیت‌هایی مثل سفارش، رزرو یا درخواست فعال شوند، اینجا نمایش داده می‌شوند."
            />
          )}
        </SheetContent>
      </Sheet>

      <Sheet open={sheet === "more"} onOpenChange={(o) => !o && close()}>
        <SheetContent side="bottom" className="gap-4 px-4 pt-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
          <SheetHeader>
            <SheetTitle>بیشتر</SheetTitle>
            <SheetDescription className="sr-only">ساخت ربات، تنظیمات، کسب‌وکار و حساب</SheetDescription>
          </SheetHeader>
          <div className="rounded-sm border">
            <BusinessSwitcher onNavigate={close} className="min-h-11" />
          </div>
          {extraInsights && extraInsights.items.length > 0 && (
            <NavGroupList group={extraInsights} pathname={pathname} badges={badges} onNavigate={close} large />
          )}
          {build && <NavGroupList group={build} pathname={pathname} badges={badges} onNavigate={close} large />}
          {settings && <NavGroupList group={settings} pathname={pathname} badges={badges} onNavigate={close} large />}
          <div className="border-t pt-4">
            <ThemeChoice />
          </div>
          <button
            type="button"
            onClick={() => {
              close();
              void signOut();
            }}
            className="flex min-h-11 items-center gap-3 rounded-sm px-3 text-small font-medium text-fg-secondary hover:bg-surface-sunken hover:text-fg"
          >
            <LogOut className="size-5 rtl:-scale-x-100" strokeWidth={1.75} aria-hidden />
            خروج
          </button>
        </SheetContent>
      </Sheet>
    </>
  );
}
