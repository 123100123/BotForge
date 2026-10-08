"use client";

import { Direction } from "radix-ui";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/lib/theme";

/** Client-side providers for the root layout: Radix direction (RTL), theme, tooltip delay. */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <Direction.Provider dir="rtl">
      <ThemeProvider>
        <TooltipProvider>{children}</TooltipProvider>
      </ThemeProvider>
    </Direction.Provider>
  );
}
