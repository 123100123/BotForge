"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import {
  Check,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CirclePause,
  Info,
  LoaderCircle,
  MessageCircleQuestionMark,
  Minus,
  Pause,
  RotateCcw,
  TriangleAlert,
  WifiOff,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  activeLabel,
  currentStep,
  retryInfo,
  runFailure,
  runSummary,
  type PendingOwnerMessage,
  type RunStep,
  type RunView,
  type StepState,
} from "@/lib/agent-state";
import { fa, formatDuration } from "@/lib/format";
import type { RunStatus as RunStatusValue } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ActivityTimeline } from "./activity-timeline";
import { FAILURE_TITLES, retryReasonLabel } from "./labels";

/** No event for this long while heartbeats still arrive: the server is alive and the model is thinking. */
export const MODEL_QUIET_MS = 20_000;
/** Bytes older than this mean the connection is dead (the stream watchdog reconnects at the same age). */
export const BYTES_STALE_MS = 35_000;

export interface RunStatusAgent {
  status: RunStatusValue | null;
  view: RunView;
  steps: RunStep[];
  pending: PendingOwnerMessage | null;
  connection: "open" | "reconnecting";
  lastBytesAt: number | null;
  lastEventAt: number | null;
  busy: boolean;
  retry: () => Promise<void>;
  resend: () => Promise<boolean>;
  dismissPending: () => void;
}

/** Re-renders every `everyMs` while `active`; the live region does not depend on it, so screen readers hear states, not ticks. */
function useNow(active: boolean, everyMs = 5000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(timer);
  }, [active, everyMs]);
  return now;
}

type Tone = "neutral" | "brand" | "success" | "warning" | "danger";

interface Headline {
  tone: Tone;
  icon: ReactNode;
  /** The state in one sentence. This is what the live region announces. */
  sentence: string;
  /** What the assistant is doing right now, or a hint; not announced. */
  detail: string | null;
}

const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-fg-secondary",
  brand: "text-brand-text",
  success: "text-success-text",
  warning: "text-warning-text",
  danger: "text-danger-text",
};

const ICON = "mt-1 size-5 shrink-0";

/** Which sentence the header shows, from the run's state. Pure. */
export function headlineFor(agent: RunStatusAgent): Headline {
  const { status, view, steps, pending } = agent;
  const asAnswer = pending?.target === "existing";
  if (pending?.state === "sending") {
    return {
      tone: "brand",
      icon: <LoaderCircle strokeWidth={1.75} aria-hidden className={cn(ICON, "motion-safe:animate-spin")} />,
      sentence: asAnswer ? "در حال ارسال پاسخ شما…" : "در حال ارسال درخواست شما…",
      detail: null,
    };
  }
  if (pending?.state === "failed") {
    return {
      tone: "danger",
      icon: <CircleAlert strokeWidth={1.75} aria-hidden className={ICON} />,
      sentence: asAnswer ? "پاسخ شما ارسال نشد" : "درخواست شما ارسال نشد",
      detail: null,
    };
  }
  if (pending?.state === "received") {
    return {
      tone: "success",
      icon: <CircleCheck strokeWidth={1.75} aria-hidden className={ICON} />,
      sentence: asAnswer ? "پاسخ شما رسید" : "درخواست شما رسید",
      detail: "دستیار همین حالا شروع می‌کند.",
    };
  }
  const step = currentStep(steps);
  switch (status) {
    case "running":
      return {
        tone: "brand",
        icon: <LoaderCircle strokeWidth={1.75} aria-hidden className={cn(ICON, "motion-safe:animate-spin")} />,
        sentence: "دستیار در حال کار است",
        detail: activeLabel(view) ?? (step ? `مرحله: ${step.label}` : null),
      };
    case "waiting_user":
      return {
        tone: "warning",
        icon: <MessageCircleQuestionMark strokeWidth={1.75} aria-hidden className={ICON} />,
        sentence: "منتظر پاسخ شماست",
        detail: "دستیار برای ادامه به جواب شما نیاز دارد.",
      };
    case "waiting_approval":
      return {
        tone: "warning",
        icon: <CirclePause strokeWidth={1.75} aria-hidden className={ICON} />,
        sentence: "آمادهٔ تأیید شماست",
        detail: "تا شما تأیید نکنید چیزی در ربات عوض نمی‌شود.",
      };
    case "done":
      return { tone: "success", icon: <CircleCheck strokeWidth={1.75} aria-hidden className={ICON} />, sentence: "انجام شد", detail: null };
    case "rejected":
      return { tone: "neutral", icon: <CircleAlert strokeWidth={1.75} aria-hidden className={ICON} />, sentence: "رد شد", detail: null };
    case "failed":
      return { tone: "danger", icon: <CircleAlert strokeWidth={1.75} aria-hidden className={ICON} />, sentence: "ناموفق", detail: null };
    case "interrupted":
      return { tone: "danger", icon: <CirclePause strokeWidth={1.75} aria-hidden className={ICON} />, sentence: "متوقف شد", detail: null };
    default:
      return { tone: "neutral", icon: <Info strokeWidth={1.75} aria-hidden className={ICON} />, sentence: "در حال بارگذاری…", detail: null };
  }
}

const STEP_WORDS: Record<StepState, string> = {
  pending: "در انتظار",
  running: "در حال انجام",
  done: "انجام شد",
  failed: "ناموفق",
  waiting_user: "منتظر شما",
  waiting_approval: "منتظر تأیید شما",
  skipped: "انجام نشد",
};

function StepMarker({ state }: { state: StepState }) {
  const base = "flex size-5 shrink-0 items-center justify-center rounded-full";
  switch (state) {
    case "pending":
      return <span aria-hidden className={cn(base, "border border-border-strong bg-surface")} />;
    case "running":
      return (
        <span aria-hidden className={cn(base, "bg-brand-soft")}>
          <span className="size-2.5 rounded-full bg-brand motion-safe:animate-pulse" />
        </span>
      );
    case "done":
      return (
        <span aria-hidden className={cn(base, "bg-success text-on-brand")}>
          <Check strokeWidth={2} className="size-3.5" />
        </span>
      );
    case "failed":
      return (
        <span aria-hidden className={cn(base, "bg-danger text-on-brand")}>
          <X strokeWidth={2} className="size-3.5" />
        </span>
      );
    case "waiting_user":
    case "waiting_approval":
      return (
        <span aria-hidden className={cn(base, "bg-warning-soft text-warning-text")}>
          <Pause strokeWidth={2} className="size-3" />
        </span>
      );
    case "skipped":
      return (
        <span aria-hidden className={cn(base, "border border-border bg-surface-sunken text-fg-muted")}>
          <Minus strokeWidth={2} className="size-3" />
        </span>
      );
  }
}

const STEP_TEXT: Record<StepState, string> = {
  pending: "text-fg-muted",
  running: "font-semibold text-fg",
  done: "text-fg",
  failed: "font-semibold text-danger-text",
  waiting_user: "font-semibold text-warning-text",
  waiting_approval: "font-semibold text-warning-text",
  skipped: "text-fg-muted line-through decoration-fg-muted/40",
};

/** The ordered steps, pending ones included. */
export function StepList({ steps, label = "مراحل کار دستیار" }: { steps: RunStep[]; label?: string }) {
  return (
    <ol aria-label={label} className="flex flex-col">
      {steps.map((step, i) => (
        <li
          key={step.key}
          data-state={step.state}
          aria-current={step.state === "running" || step.state === "waiting_user" || step.state === "waiting_approval" ? "step" : undefined}
          className="relative flex gap-3 pb-3 last:pb-0"
        >
          {i < steps.length - 1 && <span aria-hidden className="absolute start-[9.5px] top-6 bottom-0 w-px bg-border" />}
          <div className="z-10 pt-0.5">
            <StepMarker state={step.state} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2.5">
              <span className={cn("text-body", STEP_TEXT[step.state])}>{step.label}</span>
              <span className="text-caption text-fg-muted">{STEP_WORDS[step.state]}</span>
            </div>
            {step.detail && <p className="text-small text-fg-secondary">{step.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ConnectionLine({ agent, now }: { agent: RunStatusAgent; now: number }) {
  const { status, connection, lastBytesAt, lastEventAt } = agent;
  if (status !== "running" && status !== "waiting_user" && status !== "waiting_approval") return null;
  if (connection === "reconnecting") {
    return (
      <p className="flex items-start gap-2 rounded-sm bg-warning-soft p-3 text-small text-warning-text">
        <WifiOff strokeWidth={1.75} aria-hidden className="mt-1 size-4 shrink-0" />
        ارتباط قطع شد؛ در حال اتصال دوباره…
      </p>
    );
  }
  // Heartbeats keep arriving but no event: the server is alive and the model is working.
  if (
    status === "running" &&
    lastEventAt !== null &&
    lastBytesAt !== null &&
    now - lastEventAt > MODEL_QUIET_MS &&
    now - lastBytesAt < BYTES_STALE_MS
  ) {
    return (
      <p className="flex items-start gap-2 rounded-sm bg-info-soft p-3 text-small text-info-text">
        <Info strokeWidth={1.75} aria-hidden className="mt-1 size-4 shrink-0" />
        مدل هنوز در حال کار است. ارتباط برقرار است و این مرحله کمی طول می‌کشد.
      </p>
    );
  }
  return null;
}

function PendingFailure({ agent }: { agent: RunStatusAgent }) {
  const { pending } = agent;
  if (!pending || pending.state !== "failed") return null;
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-sm bg-danger-soft p-4">
      <div className="flex flex-col gap-1">
        <p className="text-body font-semibold text-danger-text">پیام شما به دستیار نرسید</p>
        <p className="text-body text-danger-text">{pending.error}</p>
        <p className="text-small text-danger-text">چیزی در ربات تغییر نکرد؛ متن شما نگه داشته شده است.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" loading={agent.busy} onClick={() => void agent.resend()}>
          <RotateCcw strokeWidth={1.75} aria-hidden />
          ارسال دوباره
        </Button>
        <Button size="sm" variant="secondary" disabled={agent.busy} onClick={agent.dismissPending}>
          حذف پیام
        </Button>
      </div>
    </div>
  );
}

function FailureBlock({ agent }: { agent: RunStatusAgent }) {
  const failure = runFailure(agent.view);
  if (!failure) return null;
  const failedStep = agent.steps.find((s) => s.state === "failed");
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-sm bg-danger-soft p-4">
      <div className="flex flex-col gap-1">
        <p className="flex items-start gap-2 text-body font-semibold text-danger-text">
          <TriangleAlert strokeWidth={1.75} aria-hidden className="mt-1 size-4 shrink-0" />
          {FAILURE_TITLES[failure.code]}
        </p>
        {failure.message && failure.message !== FAILURE_TITLES[failure.code] && (
          <p className="text-body text-danger-text">{failure.message}</p>
        )}
        {failedStep && <p className="text-small text-danger-text">مرحلهٔ «{failedStep.label}»</p>}
        {failure.applied === false && <p className="text-body font-medium text-danger-text">چیزی در ربات تغییر نکرد.</p>}
      </div>
      {failure.retryable && (
        <div>
          <Button size="sm" loading={agent.busy} onClick={() => void agent.retry()}>
            <RotateCcw strokeWidth={1.75} aria-hidden />
            تلاش دوباره
          </Button>
        </div>
      )}
    </div>
  );
}

/** Whether the run is over (its block collapses to a summary line). */
function isOver(status: RunStatusValue | null): boolean {
  return status === "done" || status === "failed" || status === "rejected" || status === "interrupted";
}

/** «انجام شد در ۱ دقیقه و ۴۰ ثانیه · ۲۵ از ۲۵ آزمون موفق» */
function summaryLine(agent: RunStatusAgent, sentence: string): string {
  const { workedMs, tests } = runSummary(agent.view);
  const parts: string[] = [];
  parts.push(workedMs !== null && (agent.status === "done" || agent.status === "failed") ? `${sentence} در ${formatDuration(workedMs)}` : sentence);
  if (tests) parts.push(`${fa(tests.passed)} از ${fa(tests.total)} آزمون موفق`);
  return parts.join(" · ");
}

/**
 * The honest status of the assistant's work: what state the run is in right now (received, working,
 * waiting for you, failed, stopped, done), what it is doing, whether the connection is alive, and the whole
 * step list with the steps still to come. While the run is open the steps stay visible; once it is over the
 * block collapses to one line with «مشاهدهٔ فعالیت» (steps and the technical timeline). Only the headline and
 * the connection line are in the live region, so a screen reader hears state changes, not progress ticks.
 */
export function RunStatus({
  agent,
  className,
  standalone = false,
}: {
  agent: RunStatusAgent;
  className?: string;
  /** Only the owner's pending message exists (no run of its own yet): no steps, no connection line. */
  standalone?: boolean;
}) {
  const { status, view, steps, pending } = agent;
  const over = !standalone && pending === null && isOver(status);
  const now = useNow(!over && status !== null);
  const [showActivity, setShowActivity] = useState(false);
  const activityId = useId();
  const headline = headlineFor(agent);
  const retry = retryInfo(view);
  const hasSteps = !standalone && steps.length > 0;

  return (
    <section
      aria-label="وضعیت کار دستیار"
      data-run-state={pending ? `pending-${pending.state}` : (status ?? "none")}
      className={cn("flex flex-col gap-4 border-t border-border px-5 py-5", className)}
    >
      <div className="flex flex-col gap-3" role="status" aria-live="polite" aria-atomic="false">
        <div className="flex items-start gap-2.5">
          <span className={TONE_TEXT[headline.tone]}>{headline.icon}</span>
          <div className="min-w-0 flex-1">
            <p className={cn("text-h3", TONE_TEXT[headline.tone])}>{over ? summaryLine(agent, headline.sentence) : headline.sentence}</p>
          </div>
        </div>
        {/* the connection line is part of the live region: losing the connection is a state change */}
        {!over && !standalone && <ConnectionLine agent={agent} now={now} />}
      </div>

      {!over && headline.detail && <p className="ps-[30px] text-body text-fg-secondary">{headline.detail}</p>}
      {retry && (
        <p className="flex items-start gap-2 rounded-sm bg-surface-sunken p-3 text-small text-fg-secondary">
          <RotateCcw strokeWidth={1.75} aria-hidden className="mt-1 size-4 shrink-0" />
          دستیار دوباره تلاش می‌کند (تلاش {fa(retry.attempt)})؛ {retryReasonLabel(retry.reason)}.
        </p>
      )}

      <PendingFailure agent={agent} />
      <FailureBlock agent={agent} />

      {over ? (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            aria-expanded={showActivity}
            aria-controls={activityId}
            onClick={() => setShowActivity((v) => !v)}
            className="-mx-2 flex min-h-11 w-fit items-center gap-1.5 rounded-sm px-2 text-small font-medium text-brand-text transition-colors duration-fast hover:bg-surface-sunken"
          >
            مشاهدهٔ فعالیت
            <ChevronDown strokeWidth={1.75} aria-hidden className={cn("size-4 transition-transform duration-fast", showActivity && "rotate-180")} />
          </button>
          <div id={activityId} hidden={!showActivity} className="flex flex-col gap-5">
            {showActivity && (
              <>
                <StepList steps={steps} />
                <div className="flex flex-col gap-2">
                  <h4 className="text-small font-semibold text-fg">جزئیات فنی</h4>
                  <ActivityTimeline phases={view.phases} variant="technical" label="مراحل و گام‌های فنی دستیار" />
                </div>
              </>
            )}
          </div>
        </div>
      ) : (
        hasSteps && (
          <>
            <StepList steps={steps} />
            <TechnicalDetails view={view} />
          </>
        )
      )}
    </section>
  );
}

/** The tool-level timeline of an open run, collapsed. */
function TechnicalDetails({ view }: { view: RunView }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (view.phases.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="-mx-2 flex min-h-11 w-fit items-center gap-1.5 rounded-sm px-2 text-small font-medium text-fg-secondary transition-colors duration-fast hover:bg-surface-sunken"
      >
        جزئیات فنی
        <ChevronDown strokeWidth={1.75} aria-hidden className={cn("size-4 transition-transform duration-fast", open && "rotate-180")} />
      </button>
      <div id={id} hidden={!open}>
        {open && <ActivityTimeline phases={view.phases} variant="technical" label="مراحل و گام‌های فنی دستیار" />}
      </div>
    </div>
  );
}
