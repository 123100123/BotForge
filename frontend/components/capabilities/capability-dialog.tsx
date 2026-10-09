"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { ErrorNote } from "@/components/app/state-blocks";
import type { WorkspaceTab } from "@/components/app/workspace";
import { CapabilityConfig, hasConfigFields } from "@/components/capabilities/capability-config";
import { AUDIENCE_LABELS, COMING_SOON, metricLabel, namesOf, openSection } from "@/components/capabilities/labels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { ToggleField } from "@/components/data/controls";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/errors";
import type { CapabilityOut, CapabilityToggleOut } from "@/lib/types";

export interface ToggleSuccess {
  capabilityName: string;
  action: "enable" | "disable";
  revisionNumber: number | null;
  message: string;
}

type Phase =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "plan"; out: CapabilityToggleOut }
  | { kind: "applying"; out: CapabilityToggleOut };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

/** Detail panel of one capability: what it is, what it needs and adds, its config, and the toggle with a dry-run plan before anything changes. */
export function CapabilityDialog({
  botId,
  cap,
  byId,
  onClose,
  onCapabilityUpdated,
  onToggled,
  onOpenTab,
}: {
  botId: string;
  cap: CapabilityOut;
  byId: Map<string, CapabilityOut>;
  onClose: () => void;
  onCapabilityUpdated: (cap: CapabilityOut) => void;
  onToggled: (result: ToggleSuccess) => void;
  onOpenTab?: (tab: WorkspaceTab) => void;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const [configBusy, setConfigBusy] = useState(false);
  /** The handoff was refused because an agent run is already open: offer to go to it. */
  const [runActive, setRunActive] = useState(false);
  const soon = COMING_SOON.has(cap.id);
  const action = cap.enabled ? "disable" : "enable";
  const busy = phase.kind === "checking" || phase.kind === "applying";
  const closingBlocked = busy || handoffBusy || configBusy;

  function fail(err: unknown) {
    const text = errorMessage(err);
    // 409 on a toggle: the new revision failed compatibility or its tests and was never activated.
    setError(
      err instanceof ApiError && err.status === 409
        ? `${text} نسخهٔ جدید فعال نشد و ربات مثل قبل کار می‌کند.`
        : text,
    );
  }

  async function call(dryRun: boolean): Promise<CapabilityToggleOut> {
    const body = { dry_run: dryRun };
    return action === "enable" ? api.enableCapability(botId, cap.id, body) : api.disableCapability(botId, cap.id, body);
  }

  async function preview() {
    setError(null);
    setPhase({ kind: "checking" });
    try {
      setPhase({ kind: "plan", out: await call(true) });
    } catch (err) {
      fail(err);
      setPhase({ kind: "idle" });
    }
  }

  async function confirm(out: CapabilityToggleOut) {
    setError(null);
    setPhase({ kind: "applying", out });
    try {
      const result = await call(false);
      if (result.applied) {
        onToggled({
          capabilityName: cap.name,
          action,
          revisionNumber: result.revision_number,
          message: result.message,
        });
        return;
      }
      // Not applied (for example the plan changed since the preview): show the new plan and the backend's reason.
      setPhase({ kind: "plan", out: result });
      setError(result.message);
    } catch (err) {
      fail(err);
      setPhase({ kind: "plan", out });
    }
  }

  async function handoff(prompt: string) {
    setHandoffBusy(true);
    setError(null);
    setRunActive(false);
    try {
      await api.createRun(botId, prompt);
      onClose();
      openSection("copilot", onOpenTab);
    } catch (err) {
      setError(errorMessage(err));
      setRunActive(err instanceof ApiError && err.status === 409);
    } finally {
      setHandoffBusy(false);
    }
  }

  const plan = phase.kind === "plan" || phase.kind === "applying" ? phase.out.plan : null;
  const verb = plan?.action === "disable" ? "غیرفعال" : "فعال";

  return (
      <Modal.Backdrop isOpen onOpenChange={(open) => !open && !closingBlocked && onClose()} isDismissable={!closingBlocked} isKeyboardDismissDisabled={closingBlocked}>
        <Modal.Container size="lg" scroll="inside" className="max-h-[90dvh]">
          <Modal.Dialog className="max-h-[90dvh] gap-5 overflow-y-auto">
        <Button isIconOnly size="sm" variant="ghost" aria-label="بستن" className="absolute end-4 top-4" isDisabled={closingBlocked} onPress={onClose}><X className="size-4" /></Button>
        <Modal.Header>
          <div className="flex flex-wrap items-center gap-2 pe-12">
            <Modal.Heading className="leading-7">{cap.name}</Modal.Heading>
            {soon ? (
              <Badge variant="warning">به‌زودی</Badge>
            ) : (
              <Badge variant={cap.enabled ? "success" : "secondary"}>{cap.enabled ? "● فعال" : "○ غیرفعال"}</Badge>
            )}
          </div>
          <p className="text-sm leading-7 text-muted-foreground">{cap.description}</p>
        </Modal.Header>

        {cap.features.length > 0 && (
          <Section title="امکانات">
            <ul className="flex list-disc flex-col gap-1 ps-5 text-sm leading-7 marker:text-muted-foreground">
              {cap.features.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </Section>
        )}

        {(cap.requires.length > 0 || cap.requires_any.length > 0 || cap.conflicts.length > 0) && (
          <Section title="وابستگی‌ها">
            <ul className="flex flex-col gap-1 text-sm leading-7">
              {cap.requires.length > 0 && <li>نیاز دارد به {namesOf(cap.requires, byId)}</li>}
              {cap.requires_any.length > 0 && <li>حداقل یکی از این‌ها لازم است: {namesOf(cap.requires_any, byId)}</li>}
              {cap.conflicts.length > 0 && <li>با این‌ها هم‌زمان کار نمی‌کند: {namesOf(cap.conflicts, byId)}</li>}
            </ul>
          </Section>
        )}

        {cap.metrics.length > 0 && (
          <Section title="شاخص‌هایی که اضافه می‌کند">
            <ul className="flex flex-wrap gap-1.5">
              {cap.metrics.map((m) => (
                <li key={m}>
                  <Badge variant="outline">{metricLabel(m)}</Badge>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {cap.audience !== null && (
          <Section title="مخاطب">
            <p className="text-sm">{AUDIENCE_LABELS[cap.audience] ?? cap.audience}</p>
          </Section>
        )}

        {hasConfigFields(cap) && (
          <Section title="تنظیمات">
            {cap.enabled ? (
              <CapabilityConfig key={cap.id} botId={botId} cap={cap} onSaved={onCapabilityUpdated} onBusyChange={setConfigBusy} />
            ) : (
              <p className="text-sm leading-7 text-muted-foreground">پس از فعال‌کردن قابلیت می‌توانید آن را تنظیم کنید.</p>
            )}
          </Section>
        )}

        <div className="flex flex-col gap-3 border-t pt-4">
          {soon ? (
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm leading-7 text-muted-foreground">این قابلیت به‌زودی اضافه می‌شود.</p>
              <ToggleField id={`soon-${cap.id}`} label={`فعال‌سازی ${cap.name}`} value={false} onChange={() => {}} isDisabled />
            </div>
          ) : plan === null ? (
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm leading-7 text-muted-foreground">
                {cap.enabled
                  ? "قبل از غیرفعال‌کردن، پیش‌نمایش تغییرات را می‌بینید."
                  : "قبل از فعال‌کردن، پیش‌نمایش تغییرات را می‌بینید."}
              </p>
              <Button variant={cap.enabled ? "outline" : "primary"} isDisabled={busy} onPress={preview}>
                {phase.kind === "checking" ? "در حال بررسی…" : cap.enabled ? "غیرفعال‌کردن" : "فعال‌کردن"}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-3" aria-live="polite">
              {plan.blocked_by.length > 0 ? (
                <ErrorNote>
                  {verb}‌کردن {cap.name} در حال حاضر ممکن نیست؛ این قابلیت‌ها مانع هستند: {namesOf(plan.blocked_by, byId)}
                </ErrorNote>
              ) : plan.needs_agent ? (
                <div className="flex flex-col gap-2 rounded-md bg-warning/15 p-3 text-sm leading-7">
                  <p className="font-semibold text-warning">این قابلیت نیاز به پیکربندی دارد</p>
                  <p>برای فعال‌کردن {cap.name} باید چند چیز مشخص شود. دستیار هوشمند از شما می‌پرسد و آن را راه‌اندازی می‌کند.</p>
                </div>
              ) : (
                <p className="text-sm leading-7">
                  {verb === "فعال"
                    ? plan.will_enable.length > 0
                      ? `با فعال‌کردن ${cap.name}، این‌ها هم فعال می‌شوند: ${namesOf(plan.will_enable, byId)}.`
                      : `فقط ${cap.name} فعال می‌شود و قابلیت دیگری تغییر نمی‌کند.`
                    : plan.will_disable.length > 0
                      ? `با غیرفعال‌کردن ${cap.name}، این‌ها هم غیرفعال می‌شوند (چون به آن وابسته‌اند): ${namesOf(plan.will_disable, byId)}.`
                      : `فقط ${cap.name} غیرفعال می‌شود و قابلیت دیگری تغییر نمی‌کند.`}
                </p>
              )}
              {plan.compat_warnings.length > 0 && (
                <ul className="flex flex-col gap-1 rounded-md bg-warning/15 p-3 text-sm leading-7 text-warning">
                  {plan.compat_warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
              {plan.blocked_by.length === 0 && !plan.needs_agent && (
                <p className="text-xs leading-6 text-muted-foreground">
                  {cap.kind === "spec"
                    ? "این تغییر یک نسخهٔ جدید از ربات می‌سازد؛ فقط اگر آزمون‌ها موفق باشند فعال می‌شود و از بخش نسخه‌ها قابل بازگشت است."
                    : "این تغییر بلافاصله اعمال می‌شود."}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                {plan.blocked_by.length === 0 && plan.needs_agent && (
                  <Button isDisabled={handoffBusy} onPress={() => handoff(plan.handoff_prompt ?? cap.handoff_prompt ?? `قابلیت «${cap.name}» را برای ربات فعال کن.`)}>
                    {handoffBusy ? "در حال شروع…" : "ادامه با دستیار"}
                  </Button>
                )}
                {plan.blocked_by.length === 0 && !plan.needs_agent && (
                  <Button
                    variant={plan.action === "disable" ? "danger" : "primary"}
                    isDisabled={phase.kind === "applying"}
                    onPress={() => phase.kind === "plan" && confirm(phase.out)}
                  >
                    {phase.kind === "applying" ? "در حال اعمال…" : plan.action === "disable" ? "تأیید و غیرفعال‌کردن" : "تأیید و فعال‌کردن"}
                  </Button>
                )}
                <Button variant="outline" isDisabled={phase.kind === "applying"} onPress={() => setPhase({ kind: "idle" })}>
                  {plan.blocked_by.length > 0 ? "بازگشت" : "انصراف"}
                </Button>
              </div>
            </div>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
          {runActive && (
            <Button
              variant="outline"
              className="self-start"
              onPress={() => {
                onClose();
                openSection("copilot", onOpenTab);
              }}
            >
              باز کردن دستیار
            </Button>
          )}
        </div>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
  );
}
