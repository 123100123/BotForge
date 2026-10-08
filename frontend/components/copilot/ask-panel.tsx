"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { FileBarChartIcon, Loader2Icon, PencilLineIcon, SendHorizontalIcon } from "lucide-react";
import { useAgentRunContext } from "@/components/agent/agent-run-provider";
import { Segmented } from "@/components/app/segmented";
import { useOptionalBusiness } from "@/components/app/business-context";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { toFaDigits } from "@/lib/format";
import { sectionHref } from "@/lib/routes";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";
import { useAssistant } from "./assistant-provider";
import { answerSources, suggestedQuestions } from "./sources";
import type { AskThread } from "./use-ask-thread";

type Mode = "ask" | "change";

const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: "ask", label: "پرسش" },
  { value: "change", label: "درخواست تغییر" },
];

const CHANGE_HELP = "این پیام یک پیشنهاد تغییر می‌سازد؛ تا شما تأیید نکنید چیزی در ربات عوض نمی‌شود.";

/** Question chips (also used by the Overview). */
export function SuggestionChips({ questions, onPick, disabled }: { questions: string[]; onPick: (q: string) => void; disabled?: boolean }) {
  return (
    <ul className="flex flex-wrap gap-2" aria-label="پرسش‌های پیشنهادی">
      {questions.map((q) => (
        <li key={q}>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(q)}
            className="rounded-sm border border-border-strong bg-surface px-3 py-1.5 text-start text-small text-fg transition-colors duration-fast hover:bg-surface-sunken disabled:pointer-events-none disabled:opacity-50"
          >
            {q}
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * The assistant panel's content: questions (read-only answers with the sources they used) and, through the
 * mode switch, change requests that become a proposal on the Changes page. The thread state comes from the
 * caller (AssistantProvider) so it persists; a change request goes to the agent run controller.
 */
export function AskPanel({
  thread,
  onOpenCapabilities,
  inputId,
}: {
  thread: AskThread;
  onOpenCapabilities: () => void;
  /** id of the question box, so the panel can focus it when it opens. */
  inputId?: string;
}) {
  const { turns, draft, setDraft, busy, failure, ask, retry } = thread;
  const business = useOptionalBusiness();
  const run = useAgentRunContext();
  const assistant = useAssistant();
  const router = useRouter();
  const fullScreen = useMediaQuery("(max-width: 639.98px)");
  const [mode, setMode] = useState<Mode>("ask");
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const botId = business?.bot.id ?? "";
  const changesHref = sectionHref(botId, "changes");
  const questions = suggestedQuestions(business?.capabilities ?? []);
  const changeBlocked = run.awaitingOwner || run.status === "running" || run.busy;
  const change = mode === "change";

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns, busy, failure]);

  async function submitChange() {
    const text = draft.trim();
    if (!text || changeBlocked || sending) return;
    setSending(true);
    await run.send(text);
    setDraft("");
    setSending(false);
    setMode("ask");
    assistant.close();
    router.push(changesHref);
  }

  function submit() {
    if (change) void submitChange();
    else ask(draft);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  function asChange(text: string) {
    setDraft(text);
    setMode("change");
    requestAnimationFrame(() => document.getElementById(inputId ?? "")?.focus());
  }

  const lastIsUser = turns.length > 0 && turns[turns.length - 1].role === "user";
  const submitDisabled = draft.trim() === "" || (change ? changeBlocked : busy);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {turns.length === 0 ? (
        <div className="flex flex-1 flex-col justify-center gap-4 py-2">
          <div className="flex flex-col gap-1">
            <h3 className="text-h3 text-fg">از دستیارتان بپرسید</h3>
            <p className="text-small text-fg-secondary">
              دستیار از داده‌های کسب‌وکار پاسخ می‌دهد و چیزی را تغییر نمی‌دهد. یکی از پرسش‌ها را امتحان کنید یا سؤال خودتان را بنویسید.
            </p>
          </div>
          <SuggestionChips questions={questions} disabled={busy || change} onPick={(q) => ask(q)} />
        </div>
      ) : (
        <ul className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto" aria-live="polite" aria-label="گفتگو با دستیار">
          {turns.map((t, i) => {
            if (t.role === "user") {
              return (
                <li key={i} className="flex max-w-[90%] flex-col items-start gap-1 self-start">
                  <p className="rounded-md bg-brand-soft px-3 py-2 text-body whitespace-pre-wrap break-words text-fg">{t.content}</p>
                  <button
                    type="button"
                    onClick={() => asChange(t.content)}
                    className="inline-flex items-center gap-1 rounded-xs px-1 text-caption text-fg-muted underline-offset-4 transition-colors duration-fast hover:text-brand-text hover:underline"
                  >
                    <PencilLineIcon className="size-3.5" strokeWidth={1.75} aria-hidden />
                    ثبت به‌عنوان درخواست تغییر
                  </button>
                </li>
              );
            }
            const sources = answerSources(t.toolCalls);
            return (
              <li key={i} className="flex flex-col gap-2 ps-1">
                <p className="text-body whitespace-pre-wrap break-words text-fg">{toFaDigits(t.content)}</p>
                {sources.labels.length > 0 && (
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-fg-muted">
                    <span>بر اساس: {sources.labels.join("، ")}</span>
                    {sources.hasReport && botId && (
                      <Link
                        href={sectionHref(botId, "reports")}
                        onClick={() => fullScreen && assistant.close()}
                        className="inline-flex items-center gap-1 rounded-xs font-medium text-brand-text underline-offset-4 hover:underline"
                      >
                        <FileBarChartIcon className="size-3.5" strokeWidth={1.75} aria-hidden />
                        باز کردن گزارش
                      </Link>
                    )}
                  </p>
                )}
              </li>
            );
          })}
          {busy && (
            <li role="status" className="flex items-center gap-2 text-small text-fg-muted">
              <Loader2Icon className="size-4 animate-spin" strokeWidth={1.75} aria-hidden />
              دستیار در حال بررسی است…
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
          <Button variant="secondary" size="sm" onClick={onOpenCapabilities}>
            فعال‌سازی در قابلیت‌ها
          </Button>
        </div>
      )}
      {failure && failure.kind !== "disabled" && (
        <div className="flex flex-col items-start gap-2">
          <ErrorNote className="w-full">{failure.message}</ErrorNote>
          {lastIsUser && failure.kind !== "limit" && (
            <Button variant="secondary" size="sm" disabled={busy} onClick={retry}>
              تلاش دوباره
            </Button>
          )}
        </div>
      )}

      <form
        onSubmit={onSubmit}
        data-mode={mode}
        className={cn(
          "flex flex-col gap-3 rounded-md border p-3 transition-colors duration-fast",
          change ? "border-brand bg-brand-soft" : "border-border bg-surface",
        )}
      >
        <Segmented<Mode> label="نوع پیام" value={mode} onChange={setMode} options={MODE_OPTIONS} />
        {change && <p className="text-small text-fg-secondary">{CHANGE_HELP}</p>}
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={3}
          placeholder={change ? "تغییری را که می‌خواهید توضیح دهید…" : "سؤال خود را بنویسید…"}
          aria-label={change ? "درخواست تغییر" : "پرسش از دستیار"}
          id={inputId}
          className="min-h-0 resize-none"
        />
        {change && changeBlocked && (
          <p role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-small text-warning-text">
            <span>یک پیشنهاد تغییر باز دارید.</span>
            <Link
              href={changesHref}
              onClick={() => fullScreen && assistant.close()}
              className="rounded-xs font-medium underline underline-offset-4"
            >
              رفتن به تغییرات
            </Link>
          </p>
        )}
        <p className="hidden text-caption text-fg-muted sm:block">
          <bdi>Enter</bdi> ارسال، <bdi>Shift+Enter</bdi> خط جدید
        </p>
        <Button type="submit" disabled={submitDisabled} loading={change ? sending : false} className="self-end">
          <SendHorizontalIcon className="rtl:-scale-x-100" strokeWidth={1.75} />
          {change ? "ساخت پیشنهاد تغییر" : "ارسال"}
        </Button>
      </form>
    </div>
  );
}
