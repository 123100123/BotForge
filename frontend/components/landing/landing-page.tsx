import { Blocks, ChartColumn, Headset, Store, Users, Workflow, type LucideIcon } from "lucide-react";
import { WORKSPACE_TABS } from "@/components/app/workspace";
import { Card, CardContent } from "@/components/ui/card";
import { CtaButtons, HeaderCta } from "./cta-buttons";

const STEPS = [
  { title: "توضیح کسب‌وکار", text: "به زبان خودتان بگویید کسب‌وکارتان چگونه کار می‌کند." },
  { title: "انتخاب و پیکربندی قابلیت‌ها", text: "دستیار قابلیت‌های لازم را انتخاب و پیکربندی می‌کند." },
  { title: "انتشار نسخه", text: "با انتشار نسخه، رفتار همان ربات تلگرام تغییر می‌کند." },
];

/** The five registry categories with example capabilities. Examples only: what a bot has is up to its owner. */
const CATEGORIES: { icon: LucideIcon; title: string; examples: string[] }[] = [
  { icon: Store, title: "فروش و سفارش", examples: ["کاتالوگ محصولات", "سبد خرید و سفارش‌ها", "پیگیری وضعیت سفارش"] },
  { icon: Workflow, title: "عملیات", examples: ["رزرو نوبت", "رویدادها و ثبت‌نام", "فرم‌ها و تأییدها"] },
  { icon: Users, title: "تیم", examples: ["کارکنان و نقش‌ها", "اعلان به مدیر و کارکنان", "اعلامیه‌ها"] },
  { icon: ChartColumn, title: "هوشمندی", examples: ["گزارش‌ها", "تحلیل صفحه‌گسترده", "دستیار هوشمند مالک"] },
  { icon: Headset, title: "مشتری", examples: ["اطلاعات و پرسش‌های متداول", "منوی گفتگو", "پیگیری درخواست‌ها"] },
];

const SECTION_NOTES: Record<string, string> = {
  overview: "شاخص‌ها و موارد نیازمند توجه",
  copilot: "پرسش دربارهٔ کسب‌وکار یا تغییر ربات",
  capabilities: "روشن و خاموش کردن قابلیت‌ها",
  data: "اطلاعات، سفارش‌ها و رزروها",
  reports: "گزارش و نمودار هر قابلیت",
  simulator: "امتحان ربات پیش از انتشار",
  versions: "تاریخچه، تفاوت و بازگشت",
  settings: "تلگرام، تیم، گروه‌ها و زمان‌بندی",
};

export function LandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b bg-card">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-4">
          <span className="text-base font-bold text-primary">بات‌فورج</span>
          <HeaderCta />
        </div>
      </header>

      <main className="flex-1">
        <section className="mx-auto flex w-full max-w-4xl flex-col items-center gap-6 px-4 py-14 text-center md:py-24">
          <p className="rounded-full bg-accent px-3 py-1 text-xs font-medium text-accent-foreground">مرکز کنترل کسب‌وکار در تلگرام</p>
          <h1 className="text-3xl leading-snug font-bold text-balance md:text-5xl md:leading-snug">کسب‌وکارتان را از تلگرام اداره کنید.</h1>
          <p className="text-lg font-medium text-primary">یک ربات. تمام کسب‌وکار شما. ساخته و نگهداری‌شده با هوش مصنوعی.</p>
          <p className="max-w-2xl text-base leading-8 text-muted-foreground">
            به BotForge بگویید کسب‌وکارتان چگونه کار می‌کند. ایجنت هوش مصنوعی آن یک سیستم‌عامل کسب‌وکار اختصاصی در تلگرام می‌سازد و نگهداری
            می‌کند: برای مشتریان، کارکنان، عملیات، فروش و گزارش‌گیری.
          </p>
          <p className="text-sm leading-7 text-muted-foreground">
            سفارش‌ها. رزروها. رویدادها. گزارش‌ها. فرم‌ها. یک ربات، پیکربندی‌شده دور کسب‌وکار شما.
          </p>
          <CtaButtons className="justify-center" />
        </section>

        <section aria-labelledby="how-title" className="border-y bg-card">
          <div className="mx-auto w-full max-w-6xl px-4 py-12">
            <h2 id="how-title" className="mb-6 text-center text-xl font-bold">
              چگونه کار می‌کند
            </h2>
            <ol className="grid gap-4 md:grid-cols-3">
              {STEPS.map((step, i) => (
                <li key={step.title} className="flex gap-3 rounded-xl border bg-background p-4">
                  <span
                    aria-hidden
                    className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground"
                  >
                    {"۱۲۳"[i]}
                  </span>
                  <div className="flex flex-col gap-1">
                    <h3 className="text-base font-semibold">{step.title}</h3>
                    <p className="text-sm leading-7 text-muted-foreground">{step.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section aria-labelledby="cap-title" className="mx-auto w-full max-w-6xl px-4 py-12">
          <div className="mb-6 flex flex-col items-center gap-1 text-center">
            <h2 id="cap-title" className="flex items-center gap-2 text-xl font-bold">
              <Blocks className="size-5 text-primary" aria-hidden />
              قابلیت‌هایی که روشن می‌کنید
            </h2>
            <p className="text-sm text-muted-foreground">نمونه‌هایی از هر دسته؛ هر ربات فقط قابلیت‌هایی را دارد که برایش فعال شده است.</p>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {CATEGORIES.map(({ icon: Icon, title, examples }) => (
              <li key={title}>
                <Card className="h-full gap-3">
                  <CardContent className="flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                      <Icon className="size-5 text-primary" aria-hidden />
                      <h3 className="text-base font-semibold">{title}</h3>
                    </div>
                    <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
                      {examples.map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="center-title" className="border-t bg-card">
          <div className="mx-auto w-full max-w-6xl px-4 py-12">
            <h2 id="center-title" className="mb-2 text-center text-xl font-bold">
              مرکز کنترل کسب‌وکار
            </h2>
            <p className="mx-auto mb-6 max-w-xl text-center text-sm leading-7 text-muted-foreground">
              یک پنل وب با هشت بخش، برای اداره و تغییر ربات بدون دست‌کاری فنی.
            </p>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {WORKSPACE_TABS.map(({ value, label, icon: Icon }) => (
                <li key={value} className="flex items-start gap-3 rounded-xl border bg-background p-3">
                  <Icon className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold">{label}</span>
                    <span className="text-xs leading-6 text-muted-foreground">{SECTION_NOTES[value]}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="mx-auto flex w-full max-w-4xl flex-col items-center gap-4 px-4 py-14 text-center">
          <h2 className="text-xl font-bold">کسب‌وکارتان را توضیح دهید و شروع کنید.</h2>
          <CtaButtons className="justify-center" />
        </section>
      </main>

      <footer className="border-t py-6 text-center text-xs text-muted-foreground">بات‌فورج (BotForge)</footer>
    </div>
  );
}
