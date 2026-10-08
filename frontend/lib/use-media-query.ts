"use client";

import { useSyncExternalStore } from "react";

/** True while `query` matches. Server render and the first client render answer `fallback`. */
export function useMediaQuery(query: string, fallback = false): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => fallback,
  );
}

const noop = () => () => {};

/** Apple platforms show ⌘ for the shortcut modifier; everything else Ctrl. False on the server. */
export function useIsApplePlatform(): boolean {
  return useSyncExternalStore(
    noop,
    () => /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent),
    () => false,
  );
}
