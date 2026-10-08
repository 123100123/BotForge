"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const FADE = 28;

/**
 * Horizontal scroller whose edges fade out where more content is hidden (a row of tabs that is wider than
 * the screen). Works in RTL, where scrolling starts at the right edge and `scrollLeft` is zero or negative.
 */
export function ScrollFade({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState({ left: false, right: false });

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    const pos = Math.abs(el.scrollLeft);
    const rtl = getComputedStyle(el).direction === "rtl";
    // In RTL the origin (scroll position 0) is the right edge, so hidden content at the right means pos > 0.
    const hiddenOrigin = pos > 1;
    const hiddenFar = max - pos > 1;
    setMore(rtl ? { left: hiddenFar, right: hiddenOrigin } : { left: hiddenOrigin, right: hiddenFar });
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Bring the current tab into view when the row mounts.
    el.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView({ inline: "nearest", block: "nearest" });
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [measure]);

  const mask = `linear-gradient(to right, ${more.left ? "transparent" : "black"}, black ${FADE}px, black calc(100% - ${FADE}px), ${more.right ? "transparent" : "black"})`;
  return (
    <div
      ref={ref}
      onScroll={measure}
      className={cn("overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", className)}
      style={more.left || more.right ? { maskImage: mask, WebkitMaskImage: mask } : undefined}
    >
      {children}
    </div>
  );
}
