import type { Metadata } from "next";
import localFont from "next/font/local";
import { ConfigError } from "@/components/app/config-error";
import { AuthProvider } from "@/lib/auth";
import { MISSING_CONFIG } from "@/lib/config";
import "./globals.css";

// Vazirmatn (SIL OFL) is bundled in app/fonts so builds do not depend on the network.
const vazirmatn = localFont({
  src: "./fonts/Vazirmatn-Variable.woff2",
  variable: "--font-vazirmatn",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: "بات‌فورج",
  description: "ساخت و ویرایش ربات تلگرام با گفتگو به زبان فارسی",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl" className={vazirmatn.variable}>
      <body className="min-h-dvh antialiased">
        {/* Real mode without its Supabase variables: tell the operator instead of showing fake data. */}
        {MISSING_CONFIG.length > 0 ? <ConfigError missing={MISSING_CONFIG} /> : <AuthProvider>{children}</AuthProvider>}
      </body>
    </html>
  );
}
