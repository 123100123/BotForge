"use client";

import { useRef } from "react";

/**
 * Radix returns focus on close only to a `Trigger` element. Our dialogs and sheets are mostly controlled (opened
 * from a row button, a menu item or a shortcut), so they would drop focus to the page. This remembers the
 * element that had focus when the layer opened (`onOpenAutoFocus` fires before focus moves in) and hands focus
 * back to it on close, when it is still on the page. Spread the result on the Radix `Content`.
 */
export function useRestoreFocus(handlers?: { onOpenAutoFocus?: (event: Event) => void; onCloseAutoFocus?: (event: Event) => void }) {
  const opener = useRef<Element | null>(null);
  return {
    onOpenAutoFocus: (event: Event) => {
      opener.current = document.activeElement;
      handlers?.onOpenAutoFocus?.(event);
    },
    onCloseAutoFocus: (event: Event) => {
      handlers?.onCloseAutoFocus?.(event);
      const el = opener.current;
      if (event.defaultPrevented) return;
      if (el instanceof HTMLElement && el !== document.body && el.isConnected) {
        event.preventDefault();
        el.focus();
      }
    },
  };
}
