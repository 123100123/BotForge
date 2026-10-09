"use client";

import { Check, Circle, Rocket, Send, ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WorkspaceTab } from "@/components/app/workspace";
import type { Bot } from "@/lib/types";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";

export function LaunchChecklist({ bot, onOpenTab, compact = false }: { bot: Bot; onOpenTab: (tab: WorkspaceTab) => void; compact?: boolean }) {
  const steps = [
    { label: "ساخت و تأیید نسخه", hint: "رفتار ربات را با دستیار بسازید و نسخه را تأیید کنید.", done: Boolean(bot.active_revision_id), tab: "copilot" as const, icon: Sparkles },
    { label: "اتصال ربات تلگرام", hint: "توکن ربات خودتان را در تنظیمات وارد کنید.", done: Boolean(bot.tg_username), tab: "settings" as const, icon: Send },
    { label: "اتصال حساب مدیر", hint: "پیوند مدیر را در تلگرام باز کنید تا اعلان‌ها را بگیرید.", done: bot.owner_linked, tab: "settings" as const, icon: ShieldCheck },
  ];
  const count = steps.filter((s) => s.done).length;
  return <section aria-label="چک‌لیست راه‌اندازی" className={cn("rounded-2xl border border-primary/15 bg-primary/5 p-5", compact ? "space-y-3" : "space-y-5")}>
    <div className="flex flex-wrap items-center gap-3"><Rocket className="size-5 text-primary" aria-hidden /><div className="flex-1"><h2 className="text-sm font-bold">{count === 3 ? "راه‌اندازی تکمیل شد" : "قدم‌های بعدی برای راه‌اندازی"}</h2><p className="mt-1 text-xs text-muted-foreground">{fa(count)} از {fa(steps.length)} مرحله انجام شده</p></div><span className="text-xs font-semibold text-primary">{fa(Math.round(count / 3 * 100))}٪</span></div>
    <div className="h-1.5 overflow-hidden rounded-full bg-primary/10" aria-hidden><div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${count / 3 * 100}%` }} /></div>
    <ol className={cn("grid gap-3", !compact && "xl:grid-cols-3")}>
      {steps.map(({ label, hint, done, tab, icon: Icon }) => <li key={label} className="flex items-start gap-3 rounded-xl bg-card/70 p-3">
        <span className={cn("mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg", done ? "bg-success/10 text-success" : "bg-primary/10 text-primary")}>{done ? <Check className="size-4" aria-label="انجام شده" /> : <Icon className="size-4" aria-hidden />}</span>
        <div className="min-w-0 flex-1"><p className="text-xs font-semibold">{label}</p>{!compact && <p className="mt-1 text-xs leading-6 text-muted-foreground">{hint}</p>}{!done && <Button variant="ghost" size="sm" className="mt-1 h-7 px-0 text-xs text-primary" onPress={() => onOpenTab(tab)}>ادامه این مرحله</Button>}</div>
        {!done && <Circle className="mt-1 size-3 shrink-0 text-muted-foreground" aria-hidden />}
      </li>)}
    </ol>
    {count === 3 && bot.status !== "live" && <p className="text-xs leading-6 text-muted-foreground">اتصال‌ها کامل است؛ وضعیت فعلی ربات را در بالای صفحه بررسی کنید.</p>}
  </section>;
}
