"use client";

import Link from "next/link";
import { useEffect, type ReactNode } from "react";
import { AgentRunProvider } from "@/components/agent/agent-run-provider";
import { BusinessProvider, useBusinessLoader } from "@/components/app/business-context";
import { SimpleHeader } from "@/components/app/simple-header";
import { AssistantProvider } from "@/components/copilot/assistant-provider";
import { ErrorState } from "@/components/ui/error-state";
import { writeLastBot } from "@/lib/routes";
import { AppShell } from "./app-shell";
import { ShellSkeleton } from "./shell-skeleton";

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-page">
      <SimpleHeader />
      <main id="main" className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-4 py-10">
        {children}
      </main>
    </div>
  );
}

/**
 * Everything the pages of one business share: the business data (BusinessProvider), the agent run
 * (AgentRunProvider, so a running build survives navigation), the assistant panel and the shell.
 * Mounted by app/bots/[id]/layout.tsx with key = bot id, so switching business starts fresh.
 */
export function BusinessRoot({ botId, children }: { botId: string; children: ReactNode }) {
  const { load, retry } = useBusinessLoader(botId);
  const ready = load.state === "ready";

  useEffect(() => {
    if (ready) writeLastBot(botId);
  }, [ready, botId]);

  if (load.state === "loading") return <ShellSkeleton />;

  if (load.state === "not_found") {
    return (
      <Centered>
        <div role="alert" className="flex flex-col items-center gap-3 text-center">
          <h1 className="text-h2 text-fg">این کسب‌وکار پیدا نشد</h1>
          <p className="text-small text-fg-muted">ممکن است حذف شده باشد یا به حساب دیگری تعلق داشته باشد.</p>
          <Link href="/bots?all=1" className="rounded-xs text-small font-medium text-brand-text hover:underline">
            رفتن به کسب‌وکارهای شما
          </Link>
        </div>
      </Centered>
    );
  }

  if (load.state === "error") {
    return (
      <Centered>
        <ErrorState title="کسب‌وکار بارگذاری نشد" message={load.message} onRetry={retry} />
        <Link href="/bots?all=1" className="self-center rounded-xs text-small font-medium text-brand-text hover:underline">
          رفتن به کسب‌وکارهای شما
        </Link>
      </Centered>
    );
  }

  const business = load.value;
  return (
    <BusinessProvider value={business}>
      <AgentRunProvider botId={botId} onDeployed={business.reload}>
        <AssistantProvider botId={botId}>
          <AppShell>{children}</AppShell>
        </AssistantProvider>
      </AgentRunProvider>
    </BusinessProvider>
  );
}
