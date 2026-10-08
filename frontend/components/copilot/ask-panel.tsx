"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ChevronDown, Loader2, SendHorizontal, Wrench } from "lucide-react";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import type { WorkspaceTab } from "@/components/app/workspace";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/errors";
import { fa, formatNumber, toFaDigits } from "@/lib/format";
import type { Bot, ChatTurn, CopilotMessageOut, ToolCallOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Only the most recent turns are sent, so a long conversation does not grow every request. */
export const HISTORY_LIMIT = 12;

export const SUGGESTIONS = [
  "فروش این هفته چطور بود؟",
  "کدام محصول کمترین فروش را داشت؟",
  "چند نفر برای رویداد بعدی ثبت‌نام کرده‌اند؟",
  "کی امروز گزارش نفرستاده؟",
  "درخواست‌های در انتظار تأیید",
];

interface AskTurn extends ChatTurn {
  toolCalls?: ToolCallOut[];
  usage?: Record<string, unknown>;
}

type Failure = { kind: "disabled" | "limit" | "unavailable" | "other"; message: string };

function classify(err: unknown): Failure {
  if (err instanceof ApiError) {
    if (err.status === 409 && err.code === "capability_disabled") {
      return { kind: "disabled", message: "برای پاسخ به این پرسش، قابلیت مربوط به آن در ربات فعال نیست." };
    }
    if (err.status === 429) {
      return { kind: "limit", message: "سقف پرسش‌های دستیار برای الان پر شده است؛ کمی بعد دوباره امتحان کنید." };
    }
    if (err.status === 503) return { kind: "unavailable", message: "دستیار در دسترس نیست" };
  }
  return { kind: "other", message: errorMessage(err) };
}

function formatArg(value: unknown, depth = 0): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "بله" : "خیر";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return toFaDigits(value.length > 80 ? `${value.slice(0, 80)}…` : value);
  if (Array.isArray(value)) return value.map((v) => formatArg(v, depth + 1)).join("، ");
  if (typeof value === "object") {
    if (depth > 0) return "…";
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${formatArg(v, depth + 1)}`)
      .join("؛ ");
  }
  return String(value);
}

function ToolChip({ call }: { call: ToolCallOut }) {
  const [open, setOpen] = useState(false);
  const args = Object.entries(call.arguments ?? {});
  return (
    <li className="flex flex-col gap-1">
      <button
        type="button"
        aria-expanded={open}
        disabled={args.length === 0}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex max-w-full items-center gap-1.5 self-start rounded-sm border bg-card px-2.5 py-1 text-start text-caption text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none"
      >
        <Wrench className="size-3 shrink-0" aria-hidden />
        <span className="min-w-0">{toFaDigits(call.summary)}</span>
        {args.length > 0 && (
          <ChevronDown className={cn("size-3 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
        )}
      </button>
      {open && args.length > 0 && (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 rounded-sm bg-card/60 px-3 py-2 text-caption">
          {args.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground" dir="ltr">
                {k}
              </dt>
              <dd className="break-words">{formatArg(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

function UsageFooter({ usage }: { usage: Record<string, unknown> }) {
  const num = (k: string) => (typeof usage[k] === "number" ? (usage[k] as number) : 0);
  const tokens = num("input_tokens") + num("output_tokens");
  const cost = num("cost_usd") || num("cost");
  if (tokens <= 0 && cost <= 0) return null;
  return (
    <p className="mt-2 text-caption text-muted-foreground">
      {tokens > 0 && <span>{formatNumber(tokens)} توکن</span>}
      {tokens > 0 && cost > 0 && " · "}
      {cost > 0 && (
        <span>
          هزینه: <span dir="ltr">${toFaDigits(cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2))}</span>
        </span>
      )}
    </p>
  );
}

/** Ask mode: a manager chat against POST /bots/{id}/copilot/messages. It only reads; nothing in the bot changes. */
export function AskPanel({ bot, onOpenTab }: { bot: Bot; onOpenTab: (tab: WorkspaceTab) => void }) {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns, busy, failure]);

  async function send(thread: AskTurn[]) {
    setBusy(true);
    setFailure(null);
    try {
      const messages: ChatTurn[] = thread.slice(-HISTORY_LIMIT).map(({ role, content }) => ({ role, content }));
      const out: CopilotMessageOut = await api.copilotMessage(bot.id, { messages });
      setTurns([...thread, { role: "assistant", content: out.reply, toolCalls: out.tool_calls, usage: out.usage }]);
    } catch (err) {
      setFailure(classify(err));
    } finally {
      setBusy(false);
    }
  }

  function ask(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    const next: AskTurn[] = [...turns, { role: "user", content }];
    setTurns(next);
    setDraft("");
    void send(next);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    ask(draft);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      ask(draft);
    }
  }

  const lastIsUser = turns.length > 0 && turns[turns.length - 1].role === "user";

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        {turns.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <h3 className="text-h3">از کسب‌وکارتان بپرسید</h3>
            <p className="max-w-md text-sm leading-7 text-muted-foreground">
              دستیار از داده‌های ربات پاسخ می‌دهد و چیزی را تغییر نمی‌دهد. یکی از پرسش‌های زیر را امتحان کنید یا سؤال خودتان را بنویسید.
            </p>
            <ul className="flex flex-wrap justify-center gap-2" aria-label="پرسش‌های پیشنهادی">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => ask(s)}
                    className="rounded-sm border bg-card px-3 py-1.5 text-sm transition-colors hover:bg-muted disabled:opacity-50"
                  >
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <ul className="flex max-h-[28rem] flex-col gap-3 overflow-y-auto" aria-live="polite" aria-label="گفتگو با دستیار">
            {turns.map((t, i) => (
              <li
                key={i}
                className={cn(
                  "flex max-w-[90%] flex-col rounded-md p-3 text-sm leading-7 sm:max-w-[85%]",
                  t.role === "user" ? "self-start bg-primary/10" : "self-end bg-muted",
                )}
              >
                <p className="whitespace-pre-wrap break-words">{t.role === "assistant" ? toFaDigits(t.content) : t.content}</p>
                {t.toolCalls && t.toolCalls.length > 0 && (
                  <ul className="mt-2 flex flex-col gap-1.5 border-t pt-2" aria-label="ابزارهای استفاده‌شده">
                    {t.toolCalls.map((c, j) => (
                      <ToolChip key={j} call={c} />
                    ))}
                  </ul>
                )}
                {t.usage && <UsageFooter usage={t.usage} />}
              </li>
            ))}
            {busy && (
              <li className="flex items-center gap-2 self-end rounded-md bg-muted p-3 text-sm text-muted-foreground" role="status">
                <Loader2 className="size-4 animate-spin" aria-hidden />
                در حال فکر کردن…
              </li>
            )}
            <div ref={endRef} />
          </ul>
        )}

        {failure?.kind === "disabled" && (
          <div className="flex flex-col items-start gap-2">
            <InfoNote tone="warning" className="w-full">
              {failure.message}
            </InfoNote>
            <Button variant="outline" size="sm" onClick={() => onOpenTab("capabilities")}>
              فعال‌سازی در قابلیت‌ها
            </Button>
          </div>
        )}
        {failure && failure.kind !== "disabled" && (
          <div className="flex flex-col items-start gap-2">
            <ErrorNote className="w-full">{failure.message}</ErrorNote>
            {lastIsUser && failure.kind !== "limit" && (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void send(turns)}>
                تلاش دوباره
              </Button>
            )}
          </div>
        )}

        <form onSubmit={onSubmit} className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            placeholder="سؤال خود را بنویسید… (Enter برای ارسال، Shift+Enter برای خط جدید)"
            aria-label="پرسش از کسب‌وکار"
            className="min-h-0 flex-1"
          />
          <Button type="submit" disabled={busy || draft.trim() === ""}>
            <SendHorizontal className="rtl:-scale-x-100" />
            <span className="hidden sm:inline">{busy ? "در حال فکر کردن…" : "ارسال"}</span>
            <span className="sr-only sm:hidden">ارسال</span>
          </Button>
        </form>
        {turns.length > 0 && (
          <p className="text-caption text-muted-foreground">
            {fa(Math.min(turns.length, HISTORY_LIMIT))} پیام آخر گفتگو برای دستیار ارسال می‌شود.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
