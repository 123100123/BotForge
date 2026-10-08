import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { Providers } from "@/components/app/providers";
import { Toaster } from "@/components/ui/toast";
import { AuthProvider } from "@/lib/auth";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import "./globals.css";

// Vazirmatn (SIL OFL) is bundled in app/fonts so builds do not depend on the network.
const vazirmatn = localFont({
  src: "./fonts/Vazirmatn-Variable.woff2",
  variable: "--font-vazirmatn",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: "BotForge | سیستم‌عامل کسب‌وکار در تلگرام",
  description:
    "به بات‌فورج بگویید کسب‌وکارتان چطور کار می‌کند. دستیار آن یک ربات تلگرامی اختصاصی می‌سازد و نگهداری می‌کند: برای مشتریان، کارکنان، عملیات، فروش و گزارش‌گیری.",
};

// Browser chrome color: the page background of each theme (follows the OS; the in-app choice only changes the page).
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f8f8" },
    { media: "(prefers-color-scheme: dark)", color: "#0c1012" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the inline script sets data-theme before React hydrates.
    <html lang="fa" dir="rtl" className={vazirmatn.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-dvh antialiased">
        <Providers>
          <AuthProvider>{children}</AuthProvider>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
