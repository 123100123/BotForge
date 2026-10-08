import type { Metadata } from "next";
import { LandingPage } from "@/components/landing/landing-page";

const TITLE = "بات‌فورج | کسب‌وکارتان را از تلگرام اداره کنید";
const DESCRIPTION =
  "بگویید کسب‌وکارتان چطور کار می‌کند تا دستیار بات‌فورج ربات تلگرامی بسازد که سفارش، رزرو، رویداد و گزارش را برایتان می‌گرداند.";

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  openGraph: { title: TITLE, description: DESCRIPTION, type: "website", locale: "fa_IR", siteName: "BotForge" },
};

/** Public landing page. The auth guard lives in app/bots/layout.tsx, not here. */
export default function Home() {
  return <LandingPage />;
}
