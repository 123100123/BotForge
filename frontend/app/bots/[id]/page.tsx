"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, PanelRightOpen, Send } from "lucide-react";
import { BotStatusChip } from "@/components/app/bot-status-chip";
import { CapabilitiesTab } from "@/components/capabilities/capabilities-tab";
import { CopilotTab } from "@/components/copilot/copilot-tab";
import { DataTab } from "@/components/data/data-tab";
import { OverviewTab } from "@/components/overview/overview-tab";
import { ReportsSection } from "@/components/app/reports-section";
import { WorkspaceSidebar } from "@/components/app/sidebar";
import { WORKSPACE_TABS, resolveTab, type SectionTab, type WorkspaceTab } from "@/components/app/workspace";
import { SettingsTab } from "@/components/settings/settings-tab";
import { SimulatorTab } from "@/components/simulator/simulator-tab";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { VersionsTab } from "@/components/versions/versions-tab";
import { ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { Bot } from "@/lib/types";

export default function BotWorkspacePage() {
  const params = useParams<{ id: string }>(); const botId = params.id;
  const [bot, setBot] = useState<Bot | null>(null); const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<SectionTab | null>(null); const [drawerOpen, setDrawerOpen] = useState(false);
  const openTab = useCallback((next: WorkspaceTab) => { setTab(resolveTab(next)); setDrawerOpen(false); }, []);
  const [reloadTick, setReloadTick] = useState(0); const reload = useCallback(() => setReloadTick((t) => t + 1), []);
  useEffect(() => {
    let cancelled = false;
    api.getBot(botId).then((loaded) => {
      if (cancelled) return; setBot(loaded); setError(null);
      setTab((current) => current ?? (loaded.active_revision_id ? "overview" : "copilot"));
    }, (err) => { if (!cancelled) setError(errorMessage(err)); });
    return () => { cancelled = true; };
  }, [botId, reloadTick]);
  if (error && !bot) return <div className="space-y-4"><ErrorNote>{error}</ErrorNote><Button variant="outline" onPress={reload}>تلاش دوباره</Button><Link href="/bots" className="ms-3 text-sm text-primary">بازگشت به ربات‌ها</Link></div>;
  if (!bot) return <LoadingBlock />;
  const selected = tab ?? "overview"; const current = WORKSPACE_TABS.find((item) => item.value === selected)!;
  return <div className="space-y-6">
    <div className="flex flex-col gap-4 rounded-3xl border bg-card p-5 sm:p-6">
      <Link href="/bots" className="inline-flex items-center gap-1 self-start rounded-lg text-xs text-muted-foreground hover:text-primary"><ArrowRight className="size-3.5" />همهٔ ربات‌ها</Link>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0 space-y-2"><div className="flex flex-wrap items-center gap-3"><h1 className="break-words text-2xl font-extrabold sm:text-3xl">{bot.name}</h1><BotStatusChip status={bot.status} /></div><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {bot.tg_username ? <span className="inline-flex items-center gap-1.5"><Send className="size-3.5 text-primary" /><span dir="ltr">@{bot.tg_username}</span></span> : <span>هنوز به تلگرام متصل نشده</span>}
          <span aria-hidden>·</span><span>{bot.active_revision_number !== null ? `نسخهٔ فعال ${fa(bot.active_revision_number)}` : "بدون نسخهٔ فعال"}</span>
        </div></div>
        <div className="flex flex-wrap items-center gap-2"><Button variant="secondary" size="sm" onPress={() => openTab("simulator")}>امتحان ربات</Button><Button size="sm" onPress={() => openTab("copilot")}>گفتگو با دستیار</Button></div>
      </div>
    </div>
    {error && <ErrorNote>{error}</ErrorNote>}
    <div className="flex min-w-0 items-start gap-6">
      <aside className="sticky top-24 hidden h-[calc(100dvh-7rem)] w-60 shrink-0 overflow-y-auto rounded-3xl border bg-card lg:block"><WorkspaceSidebar selected={selected} onSelect={openTab} /></aside>
      <div className="min-w-0 flex-1 space-y-5">
        <div className="flex items-center gap-3 rounded-2xl border bg-card p-3 lg:hidden"><Button variant="ghost" isIconOnly onPress={() => setDrawerOpen(true)} aria-label="باز کردن فهرست بخش‌ها"><PanelRightOpen className="size-5" /></Button><span className="text-sm font-semibold">{current.label}</span><Badge className="ms-auto" variant="outline">مرکز کنترل</Badge></div>
        <section aria-label={current.label} className="min-w-0">
          {selected === "overview" && <OverviewTab bot={bot} onOpenTab={openTab} />}
          {/* Keep the builder mounted: section navigation must not interrupt its event stream. */}
          <div hidden={selected !== "copilot"}><CopilotTab bot={bot} onBotChanged={reload} onOpenTab={openTab} /></div>
          {selected === "capabilities" && <CapabilitiesTab bot={bot} onOpenTab={openTab} onBotChanged={reload} />}
          {selected === "data" && <DataTab bot={bot} onOpenTab={openTab} />}
          {selected === "reports" && <ReportsSection bot={bot} onOpenTab={openTab} />}
          {selected === "simulator" && <SimulatorTab bot={bot} onBotChanged={reload} onOpenTab={openTab} />}
          {selected === "versions" && <VersionsTab bot={bot} onBotChanged={reload} onOpenTab={openTab} />}
          {selected === "settings" && <SettingsTab bot={bot} onBotChanged={reload} onOpenTab={openTab} />}
        </section>
      </div>
    </div>
    <Modal.Backdrop isOpen={drawerOpen} onOpenChange={setDrawerOpen} className="!justify-start">
      <Modal.Container size="sm" placement="top" className="!w-[min(20rem,90vw)] !flex-none !p-0"><Modal.Dialog className="!h-dvh !max-h-dvh !rounded-none overflow-y-auto"><Modal.Heading className="sr-only">بخش‌های ربات</Modal.Heading><WorkspaceSidebar selected={selected} onSelect={openTab} onClose={() => setDrawerOpen(false)} /></Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </div>;
}
