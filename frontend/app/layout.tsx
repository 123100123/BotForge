import type { Metadata } from "next";
import localFont from "next/font/local";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

// Vazirmatn (SIL OFL) is bundled in app/fonts so builds do not depend on the network.
const vazirmatn = localFont({
  src: "./fonts/Vazirmatn-Variable.woff2",
  variable: "--font-vazirmatn",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: "BotForge — سیستم‌عامل کسب‌وکار در تلگرام",
  description:
    "به BotForge بگویید کسب‌وکارتان چگونه کار می‌کند. ایجنت هوش مصنوعی آن یک سیستم‌عامل کسب‌وکار اختصاصی در تلگرام می‌سازد و نگهداری می‌کند: برای مشتریان، کارکنان، عملیات، فروش و گزارش‌گیری.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl" className={vazirmatn.variable}>
      <body className="min-h-dvh antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
