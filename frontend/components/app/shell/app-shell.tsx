"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { useAssistant } from "@/components/copilot/assistant-provider";
import { cn } from "@/lib/utils";
import { AppSidebar } from "./app-sidebar";
import { IconRail } from "./icon-rail";
import { MobileTabBar } from "./mobile-tab-bar";
import { SKIP_LINK_CLASS } from "./skip-link";
import { TopBar } from "./top-bar";

/**
 * The authenticated Control Center frame (D30): sidebar ≥1024px, icon rail 640–1023px, bottom tab bar
 * <640px; a sticky top bar; and the content area. On route change focus moves to the page's h1 (or the main
 * region) so screen readers announce the new page.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const mainRef = useRef<HTMLElement>(null);
  const lastPath = useRef(pathname);
  const assistant = useAssistant();

  useEffect(() => {
    // Only on navigation, not on first load (a ref of the last path is safe under Strict Mode's double effects).
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    const main = mainRef.current;
    if (!main) return;
    // Wait a frame so the new page has rendered its heading.
    const raf = requestAnimationFrame(() => {
      const target = main.querySelector<HTMLElement>("h1") ?? main;
      if (target !== main && !target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.setAttribute("data-route-focus", "");
      target.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(raf);
  }, [pathname]);

  return (
    <div className="min-h-dvh bg-page">
      <a href="#main" className={SKIP_LINK_CLASS}>
        پرش به محتوا
      </a>
      <div className="flex items-start">
        <AppSidebar />
        <IconRail />
        <div
          className={cn(
            "flex min-h-dvh min-w-0 flex-1 flex-col transition-[padding] duration-base",
            // ≥1280px the assistant panel sits beside the content instead of over it.
            assistant.isOpen && "xl:pe-[420px]",
          )}
        >
          <TopBar />
          <main
            id="main"
            ref={mainRef}
            tabIndex={-1}
            className="mx-auto flex w-full max-w-[1360px] flex-1 flex-col items-stretch gap-6 px-4 pt-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] sm:p-6"
          >
            {children}
          </main>
        </div>
      </div>
      <MobileTabBar />
    </div>
  );
}
