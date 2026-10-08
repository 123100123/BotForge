"use client";

import { I18nProvider } from "@heroui/react";
import { ThemeProvider } from "next-themes";

export function ClientProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange storageKey="botforge-theme">
      <I18nProvider locale="fa-IR">{children}</I18nProvider>
    </ThemeProvider>
  );
}
