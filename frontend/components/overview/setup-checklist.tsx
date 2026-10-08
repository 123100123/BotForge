"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronRightIcon, CircleCheckIcon, CircleDashedIcon } from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import type { SetupGaps } from "@/lib/adapters/attention";
import { fa } from "@/lib/format";
import { sectionHref } from "@/lib/routes";
import type { Bot } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Step {
  id: string;
  title: string;
  done: boolean;
  optional?: boolean;
  href: string;
  action: string;
}

/** Whether a colleague (staff or manager) has joined; null while unknown. Best effort: a failure reads as "not yet". */
function useHasColleagues(botId: string): boolean {
  const [state, setState] = useState<{ botId: string; value: boolean } | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.getTeam(botId).then(
      (team) => {
        if (!cancelled) setState({ botId, value: team.members.some((m) => m.role === "staff" || m.role === "manager") });
      },
      () => {},
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);
  return state?.botId === botId ? state.value : false;
}

/**
 * First-run panel: what is left before the business works end to end. Each step shows done or pending as an
 * icon plus a word, with a link to where it is done.
 */
export function SetupChecklist({ bot, gaps }: { bot: Bot; gaps: SetupGaps }) {
  const colleagues = useHasColleagues(bot.id);
  const steps: Step[] = [
    {
      id: "version",
      title: "توضیح کسب‌وکار و تأیید اولین نسخه",
      done: !gaps.noVersion,
      href: sectionHref(bot.id, "changes"),
      action: gaps.noVersion ? "شروع" : "مشاهده",
    },
    { id: "telegram", title: "اتصال به تلگرام", done: !gaps.noTelegram, href: sectionHref(bot.id, "telegram"), action: "اتصال" },
    { id: "owner", title: "اتصال حساب مدیر", done: !gaps.ownerNotLinked, href: sectionHref(bot.id, "telegram"), action: "اتصال" },
    { id: "team", title: "دعوت از همکاران", done: colleagues, optional: true, href: sectionHref(bot.id, "team"), action: "دعوت" },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  // The first step that is not done is the one to do next.
  const nextId = steps.find((s) => !s.done && !s.optional)?.id;

  return (
    <section aria-labelledby="setup-title" className="overflow-hidden rounded-md border border-border bg-surface">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-4">
        <h2 id="setup-title" className="text-h3 text-fg">
          راه‌اندازی کسب‌وکار
        </h2>
        <p className="text-small text-fg-muted">
          {fa(doneCount)} از {fa(steps.length)} مرحله انجام شده است
        </p>
      </div>
      <ol className="divide-y divide-border">
        {steps.map((s) => (
          <li key={s.id} className={cn("flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-3", s.id === nextId && "bg-brand-soft")}>
            {s.done ? (
              <CircleCheckIcon className="size-5 shrink-0 text-success-text" strokeWidth={1.75} aria-hidden />
            ) : (
              <CircleDashedIcon className="size-5 shrink-0 text-fg-muted" strokeWidth={1.75} aria-hidden />
            )}
            <span className={cn("min-w-0 flex-1 basis-48 text-body", s.done ? "text-fg-secondary" : "text-fg")}>
              {s.title}
              {s.optional && <span className="text-small text-fg-muted"> (اختیاری)</span>}
            </span>
            <StatusBadge tone={s.done ? "success" : "neutral"}>{s.done ? "انجام شد" : "در انتظار"}</StatusBadge>
            <Link
              href={s.href}
              className="inline-flex shrink-0 items-center gap-1 rounded-xs text-small font-medium text-brand-text underline-offset-4 hover:underline"
            >
              {s.action}
              <ChevronRightIcon className="size-4 rtl:-scale-x-100" strokeWidth={1.75} aria-hidden />
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
