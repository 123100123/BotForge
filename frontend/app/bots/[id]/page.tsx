"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { AgentTab, type WorkspaceTab } from "@/components/agent/agent-tab";
import { BotStatusChip } from "@/components/app/bot-status-chip";
import { DataTab } from "@/components/data/data-tab";
import { SettingsTab } from "@/components/settings/settings-tab";
import { SimulatorTab } from "@/components/simulator/simulator-tab";
import { TestsTab } from "@/components/tests/tests-tab";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { VersionsTab } from "@/components/versions/versions-tab";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { Bot } from "@/lib/types";

const TABS: { value: WorkspaceTab; label: string }[] = [
  { value: "agent", label: "ایجنت" },
  { value: "simulator", label: "شبیه‌ساز" },
  { value: "tests", label: "تست‌ها" },
  { value: "data", label: "داده‌ها" },
  { value: "versions", label: "نسخه‌ها" },
  { value: "settings", label: "تنظیمات" },
];

export default function BotWorkspacePage() {
  const params = useParams<{ id: string }>();
  const botId = params.id;
  const [bot, setBot] = useState<Bot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("agent");

  const [reloadTick, setReloadTick] = useState(0);
  const reload = useCallback(() => setReloadTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    api.getBot(botId).then(
      (loaded) => {
        if (cancelled) return;
        setBot(loaded);
        setError(null);
      },
      (err) => {
        if (!cancelled) setError(errorMessage(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [botId, reloadTick]);

  if (error && !bot) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
        <Link href="/bots" className="text-sm text-primary hover:underline">
          بازگشت به ربات‌ها
        </Link>
      </div>
    );
  }

  if (!bot) {
    return (
      <div className="flex flex-col gap-4" role="status" aria-label="در حال بارگذاری">
        <div className="h-8 w-56 animate-pulse rounded bg-muted" />
        <div className="h-64 animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Link href="/bots" className="inline-flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground">
          <ArrowRight className="size-4" />
          همهٔ ربات‌ها
        </Link>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-xl font-bold">{bot.name}</h1>
          <BotStatusChip status={bot.status} />
          {bot.tg_username && (
            <Badge variant="outline">
              <span dir="ltr">@{bot.tg_username}</span>
            </Badge>
          )}
          <Badge variant="outline">
            {bot.active_revision_number !== null ? `نسخهٔ فعال: ${fa(bot.active_revision_number)}` : "بدون نسخهٔ فعال"}
          </Badge>
        </div>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as WorkspaceTab)}>
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {/* The agent tab stays mounted so its event stream and state survive switching tabs. */}
        <TabsContent value="agent" forceMount className="data-[state=inactive]:hidden">
          <AgentTab bot={bot} onBotChanged={reload} onOpenTab={setTab} />
        </TabsContent>
        <TabsContent value="simulator">
          <SimulatorTab bot={bot} />
        </TabsContent>
        <TabsContent value="tests">
          <TestsTab bot={bot} />
        </TabsContent>
        <TabsContent value="data">
          <DataTab bot={bot} />
        </TabsContent>
        <TabsContent value="versions">
          <VersionsTab bot={bot} />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab bot={bot} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
