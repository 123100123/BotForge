"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpLeft, Bot as BotIcon, Search, Send, Layers, Activity } from "lucide-react";
import { BotStatusChip } from "@/components/app/bot-status-chip";
import { NewBotDialog } from "@/components/app/new-bot-dialog";
import { PageHeader, MetricCard } from "@/components/app/presentation";
import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, relativeTime } from "@/lib/format";
import type { Bot } from "@/lib/types";
export default function BotsPage() {
  const [bots, setBots] = useState<Bot[] | null>(null); const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState(""); const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    api.listBots().then((list) => { if (!cancelled) { setBots(list); setError(null); } }, (err) => { if (!cancelled) setError(errorMessage(err)); });
    return () => { cancelled = true; };
  }, [tick]);
  const visible = bots?.filter((bot) => `${bot.name} ${bot.tg_username ?? ""}`.toLocaleLowerCase("fa").includes(query.trim().toLocaleLowerCase("fa")));
  return <div className="space-y-8">
    <PageHeader level={1} eyebrow="فضای کار شما" title="کسب‌وکارتان، تحت کنترل" description="ربات‌ها را بسازید، مدیریت کنید و قدم بعدی کسب‌وکارتان را از همین‌جا بردارید." action={<NewBotDialog />} />
    {error && <div className="space-y-3"><ErrorNote>{error}</ErrorNote><Button variant="outline" onPress={() => setTick((n) => n + 1)}>تلاش دوباره</Button></div>}
    {!bots && !error && <LoadingBlock />}
    {bots && <>
      <div className="grid gap-4 sm:grid-cols-3"><MetricCard label="تمام ربات‌ها" value={fa(bots.length)} icon={<BotIcon className="size-5" />} /><MetricCard label="ربات‌های فعال" value={fa(bots.filter((b) => b.status === "live").length)} icon={<Activity className="size-5" />} tone="teal" /><MetricCard label="متصل به تلگرام" value={fa(bots.filter((b) => b.tg_username).length)} icon={<Send className="size-5" />} tone="accent" /></div>
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><h2 className="text-lg font-bold">ربات‌های من</h2><p className="mt-1 text-xs text-muted-foreground">هر ربات، یک مرکز کنترل اختصاصی</p></div><div className="relative w-full sm:w-64"><Search className="pointer-events-none absolute start-3 top-3 z-10 size-4 text-muted-foreground" /><Input aria-label="جستجوی ربات‌ها" placeholder="جستجوی نام یا نام کاربری…" value={query} onChange={(e) => setQuery(e.target.value)} className="ps-9" /></div></div>
      {bots.length === 0 ? <EmptyState title="اولین ربات کسب‌وکارتان را بسازید" action={<NewBotDialog label="ساخت اولین ربات" />}>کسب‌وکارتان را توضیح دهید؛ دستیار قابلیت‌های لازم را می‌سازد و شما پیش از انتشار آن‌ها را بررسی می‌کنید.</EmptyState> : visible?.length === 0 ? <EmptyState title="رباتی با این نام پیدا نشد" action={<Button variant="outline" onPress={() => setQuery("")}>پاک کردن جستجو</Button>}>نام دیگری را امتحان کنید.</EmptyState> : <ul className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{visible?.map((bot) => <li key={bot.id} className="min-w-0"><Link href={`/bots/${bot.id}`} className="group block h-full rounded-3xl focus-visible:outline-2 focus-visible:outline-primary"><Card className="h-full min-w-0 gap-5 rounded-3xl border p-5 transition-[border-color,box-shadow] hover:border-primary/40 hover:shadow-md sm:p-6">
        <div className="flex items-center justify-between gap-3"><span className="grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary"><BotIcon className="size-6" /></span><BotStatusChip status={bot.status} /></div>
        <div className="space-y-2"><h3 className="break-words text-lg font-bold">{bot.name}</h3><p className="text-xs text-muted-foreground">{bot.tg_username ? <span dir="ltr">@{bot.tg_username}</span> : "آماده برای اتصال به تلگرام"}</p></div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><Layers className="size-3.5" /><span>{bot.active_revision_number !== null ? `نسخهٔ فعال ${fa(bot.active_revision_number)}` : "در انتظار اولین نسخه"}</span></div>
        <div className="mt-auto flex items-center justify-between gap-2 border-t pt-4"><span className="text-[11px] text-muted-foreground">ساخته‌شده {relativeTime(bot.created_at)}</span><span className="inline-flex items-center gap-1 text-xs font-semibold text-primary">مرکز کنترل<ArrowUpLeft className="size-4 transition-transform group-hover:-translate-x-0.5" /></span></div>
      </Card></Link></li>)}</ul>}
    </>}
  </div>;
}
