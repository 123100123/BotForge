"use client";

import { useEffect, useState } from "react";
import { CircleAlertIcon, CirclePlusIcon, CircleMinusIcon, MessageSquareIcon, TriangleAlertIcon } from "lucide-react";
import { useAgentRunContext } from "@/components/agent/agent-run-provider";
import { useOpenSection } from "@/components/app/shell/use-open-section";
import { namesOf } from "@/components/capabilities/labels";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/errors";
import { useMediaQuery } from "@/lib/use-media-query";
import type { CapabilityOut, CapabilityToggleOut } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ToggleDone {
  capabilityName: string;
  action: "enable" | "disable";
  revisionNumber: number | null;
  message: string;
}

type Phase =
  | { kind: "checking" }
  | { kind: "failed"; message: string }
  | { kind: "plan"; out: CapabilityToggleOut }
  | { kind: "applying"; out: CapabilityToggleOut };

/** A titled group of capabilities inside the sheet (what also turns on, what turns off). */
function ConsequenceList({
  title,
  note,
  ids,
  byId,
  tone,
}: {
  title: string;
  note?: string;
  ids: string[];
  byId: Map<string, CapabilityOut>;
  tone: "success" | "danger";
}) {
  const Icon = tone === "success" ? CirclePlusIcon : CircleMinusIcon;
  return (
    <section className="flex flex-col gap-2">
      <h3 className={cn("text-small font-semibold", tone === "danger" ? "text-danger-text" : "text-fg")}>{title}</h3>
      {note && <p className="text-small text-fg-muted">{note}</p>}
      <ul className={cn("divide-y overflow-hidden rounded-sm border", tone === "danger" ? "divide-danger/25 border-danger/40 bg-danger-soft" : "divide-border border-border")}>
        {ids.map((id) => (
          <li key={id} className="flex items-center gap-2 px-3 py-2 text-small text-fg">
            <Icon className={cn("size-4 shrink-0", tone === "danger" ? "text-danger-text" : "text-success-text")} strokeWidth={1.75} aria-hidden />
            {byId.get(id)?.name ?? id}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Note({ tone, icon, children }: { tone: "danger" | "warning" | "info"; icon: React.ReactNode; children: React.ReactNode }) {
  const toneClass = { danger: "bg-danger-soft text-danger-text", warning: "bg-warning-soft text-warning-text", info: "bg-info-soft text-info-text" }[tone];
  return (
    <div className={cn("flex items-start gap-2 rounded-sm p-3 text-small", toneClass)}>
      <span aria-hidden className="mt-1 shrink-0 [&_svg]:size-4">
        {icon}
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/**
 * The consequence sheet: asks the server for a dry-run plan first and only then offers to confirm, so the
 * owner reads what else turns on or off before anything changes. A capability that needs the assistant
 * hands off to a change proposal instead of applying.
 */
export function ConsequenceSheet({
  botId,
  cap,
  byId,
  open,
  onClose,
  onDone,
  returnFocusTo,
}: {
  botId: string;
  cap: CapabilityOut;
  byId: Map<string, CapabilityOut>;
  open: boolean;
  onClose: () => void;
  onDone: (done: ToggleDone) => void;
  /** The control that opened the sheet (Radix only returns focus to a Trigger, and this sheet has none). */
  returnFocusTo?: React.RefObject<HTMLElement | null>;
}) {
  const openSection = useOpenSection();
  const agentRun = useAgentRunContext();
  const wide = useMediaQuery("(min-width: 640px)", true);
  // The action is fixed when the sheet opens; the list behind it may refresh while the sheet closes.
  const [action] = useState<"enable" | "disable">(cap.enabled ? "disable" : "enable");
  const [phase, setPhase] = useState<Phase>({ kind: "checking" });
  const [error, setError] = useState<string | null>(null);
  const [handoffBusy, setHandoffBusy] = useState(false);
  /** The handoff was refused because an assistant run is already open: offer to go to it. */
  const [runActive, setRunActive] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const call = (dryRun: boolean) => {
    const body = { dry_run: dryRun };
    return action === "enable" ? api.enableCapability(botId, cap.id, body) : api.disableCapability(botId, cap.id, body);
  };

  useEffect(() => {
    let cancelled = false;
    const body = { dry_run: true };
    const run = action === "enable" ? api.enableCapability(botId, cap.id, body) : api.disableCapability(botId, cap.id, body);
    run.then(
      (out) => {
        if (!cancelled) setPhase({ kind: "plan", out });
      },
      (err) => {
        if (!cancelled) setPhase({ kind: "failed", message: errorMessage(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [attempt, action, botId, cap.id]);

  function retry() {
    setPhase({ kind: "checking" });
    setAttempt((n) => n + 1);
  }

  const busy = phase.kind === "applying" || handoffBusy;
  const plan = phase.kind === "plan" || phase.kind === "applying" ? phase.out.plan : null;
  const disabling = action === "disable";

  async function confirm(out: CapabilityToggleOut) {
    setError(null);
    setPhase({ kind: "applying", out });
    try {
      const result = await call(false);
      if (result.applied) {
        onDone({ capabilityName: cap.name, action, revisionNumber: result.revision_number, message: result.message });
        return;
      }
      // Not applied (for example the plan changed since the preview): show the new plan and the backend's reason.
      setPhase({ kind: "plan", out: result });
      setError(result.message);
    } catch (err) {
      const text = errorMessage(err);
      // 409 on a toggle: the new version failed compatibility or its tests and was never activated.
      setError(err instanceof ApiError && err.status === 409 ? `${text} نسخهٔ جدید فعال نشد و ربات مثل قبل کار می‌کند.` : text);
      setPhase({ kind: "plan", out });
    }
  }

  async function handoff(prompt: string) {
    setHandoffBusy(true);
    setError(null);
    setRunActive(false);
    try {
      const run = await api.createRun(botId, prompt);
      // The run state lives in the business layout; Changes shows it.
      agentRun.attach(run);
      onClose();
      openSection("changes");
    } catch (err) {
      setError(errorMessage(err));
      setRunActive(err instanceof ApiError && err.status === 409);
    } finally {
      setHandoffBusy(false);
    }
  }

  const blockers = plan?.blocked_by ?? [];
  const blockedNeedsOne = blockers.filter((id) => cap.requires_any.includes(id));
  const blockedConflicts = blockers.filter((id) => cap.conflicts.includes(id));
  const blockedOther = blockers.filter((id) => !blockedNeedsOne.includes(id) && !blockedConflicts.includes(id));
  const blocked = blockers.length > 0;
  const needsAgent = !!plan?.needs_agent && !blocked;
  const nothingElse = !!plan && plan.will_enable.length === 0 && plan.will_disable.length === 0;

  return (
    <Sheet open={open} onOpenChange={(next) => !next && !busy && onClose()}>
      <SheetContent
        side={wide ? "end" : "bottom"}
        className={cn("gap-0 overflow-hidden p-0", wide && "w-[min(100%-2rem,28rem)]")}
        aria-busy={phase.kind === "checking" || busy}
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          const el = returnFocusTo?.current;
          if (el?.isConnected) el.focus();
        }}
        onInteractOutside={(e) => busy && e.preventDefault()}
        onEscapeKeyDown={(e) => busy && e.preventDefault()}
      >
        <SheetHeader className="p-6 pb-4">
          <SheetTitle>{disabling ? `خاموش کردن «${cap.name}»` : `روشن کردن «${cap.name}»`}</SheetTitle>
          <SheetDescription>پیش از هر تغییر، اثر آن را ببینید. تا تأیید نکنید چیزی عوض نمی‌شود.</SheetDescription>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 pb-4" aria-live="polite">
          {phase.kind === "checking" && (
            <div role="status" aria-label="در حال بررسی اثر تغییر" className="flex flex-col gap-3">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-24 rounded-sm" />
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-16 rounded-sm" />
            </div>
          )}

          {phase.kind === "failed" && (
            <Note tone="danger" icon={<CircleAlertIcon strokeWidth={1.75} />}>
              <p role="alert">{phase.message}</p>
            </Note>
          )}

          {plan && (
            <>
              {blocked && (
                <Note tone="danger" icon={<CircleAlertIcon strokeWidth={1.75} />}>
                  <p className="font-semibold">در حال حاضر نمی‌توان «{cap.name}» را {disabling ? "خاموش" : "روشن"} کرد.</p>
                  <ul className="mt-1 flex list-disc flex-col gap-1 ps-5">
                    {blockedNeedsOne.length > 0 && (
                      <li>حداقل یکی از این قابلیت‌ها باید روشن باشد: {namesOf(blockedNeedsOne, byId)}.</li>
                    )}
                    {blockedConflicts.length > 0 && (
                      <li>این قابلیت با «{namesOf(blockedConflicts, byId)}» هم‌زمان کار نمی‌کند؛ اول آن را خاموش کنید.</li>
                    )}
                    {blockedOther.length > 0 && <li>این قابلیت‌ها مانع هستند: {namesOf(blockedOther, byId)}.</li>}
                  </ul>
                </Note>
              )}

              {!blocked && plan.will_enable.length > 0 && (
                <ConsequenceList
                  title="این قابلیت‌ها هم روشن می‌شوند"
                  note={`«${cap.name}» به آن‌ها نیاز دارد.`}
                  ids={plan.will_enable}
                  byId={byId}
                  tone="success"
                />
              )}

              {!blocked && plan.will_disable.length > 0 && (
                <ConsequenceList
                  title="این قابلیت‌ها خاموش می‌شوند"
                  note={`چون به «${cap.name}» وابسته‌اند و بدون آن کار نمی‌کنند.`}
                  ids={plan.will_disable}
                  byId={byId}
                  tone="danger"
                />
              )}

              {!blocked && nothingElse && !needsAgent && (
                <p className="text-body text-fg">فقط «{cap.name}» {disabling ? "خاموش" : "روشن"} می‌شود؛ قابلیت دیگری تغییر نمی‌کند.</p>
              )}

              {needsAgent && (
                <Note tone="info" icon={<MessageSquareIcon strokeWidth={1.75} />}>
                  <p className="font-semibold">این قابلیت نیاز به پیکربندی دارد</p>
                  <p>
                    برای روشن کردن «{cap.name}» چند چیز باید مشخص شود. دستیار از شما می‌پرسد و تغییر را به‌صورت یک پیشنهاد می‌سازد؛ تا تأیید نکنید چیزی در ربات عوض نمی‌شود.
                  </p>
                </Note>
              )}

              {plan.compat_warnings.length > 0 && (
                <Note tone="warning" icon={<TriangleAlertIcon strokeWidth={1.75} />}>
                  <p className="font-semibold">نکته‌هایی که بهتر است بدانید</p>
                  <ul className="mt-1 flex list-disc flex-col gap-1 ps-5">
                    {plan.compat_warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </Note>
              )}

              {!blocked && !needsAgent && (
                <p className="text-small text-fg-muted">
                  {cap.kind === "spec"
                    ? "با تأیید، نسخهٔ تازه‌ای از ربات ساخته و فعال می‌شود؛ از بخش تغییرات می‌توانید برگردید."
                    : "این تغییر با تأیید بلافاصله اعمال می‌شود و نسخهٔ تازه‌ای ساخته نمی‌شود."}
                </p>
              )}
            </>
          )}

          {error && (
            <Note tone="danger" icon={<CircleAlertIcon strokeWidth={1.75} />}>
              <p role="alert">{error}</p>
              {runActive && (
                <Button
                  variant="link"
                  size="sm"
                  className="mt-1"
                  onClick={() => {
                    onClose();
                    openSection("changes");
                  }}
                >
                  باز کردن دستیار
                </Button>
              )}
            </Note>
          )}
        </div>

        <div className="flex gap-2 border-t border-border p-6 pt-4">
          {phase.kind === "failed" ? (
            <Button className="flex-1 sm:flex-none" onClick={retry}>
              تلاش دوباره
            </Button>
          ) : needsAgent && plan ? (
            <Button
              className="flex-1 sm:flex-none"
              loading={handoffBusy}
              onClick={() => handoff(plan.handoff_prompt ?? cap.handoff_prompt ?? `قابلیت «${cap.name}» را برای ربات روشن کن.`)}
            >
              پیکربندی با دستیار
            </Button>
          ) : plan && !blocked ? (
            <Button
              className="flex-1 sm:flex-none"
              variant={disabling ? "danger" : "primary"}
              loading={phase.kind === "applying"}
              onClick={() => phase.kind === "plan" && confirm(phase.out)}
            >
              {disabling ? "تأیید و خاموش کردن" : "تأیید و روشن کردن"}
            </Button>
          ) : null}
          <Button variant="secondary" className="flex-1 sm:flex-none" disabled={busy} onClick={onClose}>
            {blocked ? "بستن" : "انصراف"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
