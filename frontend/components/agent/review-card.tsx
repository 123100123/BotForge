"use client";

import { Check, Minus, Pencil, Plus, TriangleAlert, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { fa } from "@/lib/format";
import type { TestReportPayload } from "@/lib/agent-state";
import type {
  DiffChange,
  EventPayloads,
  Requirements,
  RiskLevel,
  SpecOutline,
  TestGroup,
  TestRef,
} from "@/lib/types";
import { CAPABILITY_TYPE_LABELS, RISK_LABELS } from "./labels";

export type ReviewDecision = "pending" | "approved" | "rejected" | "closed";

interface ReviewCardProps {
  kind: "create" | "modify";
  diff: EventPayloads["diff"] | null;
  approval: EventPayloads["approval_requested"] | null;
  requirements: Requirements | null;
  outline: SpecOutline | null;
  report: TestReportPayload | null;
  /** pending: waiting for the owner; approved/rejected: decided; closed: the run ended without a decision. */
  decision: ReviewDecision;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}

const RISK_VARIANT: Record<RiskLevel, "success" | "warning" | "destructive"> = {
  low: "success",
  medium: "warning",
  high: "destructive",
};

const CHANGE_ICON: Record<DiffChange["kind"], typeof Plus> = { added: Plus, removed: Minus, changed: Pencil };
const CHANGE_STYLE: Record<DiffChange["kind"], string> = {
  added: "bg-success/10 text-success",
  removed: "bg-destructive/10 text-destructive",
  changed: "bg-warning/15 text-warning",
};

function asList(group: TestGroup): { count: number; items: TestRef[] } {
  return typeof group === "number" ? { count: group, items: [] } : { count: group.length, items: group };
}

function TestGroupBlock({ title, group, tone }: { title: string; group: TestGroup; tone: "neutral" | "success" | "warning" }) {
  const { count, items } = asList(group);
  return (
    <div className="rounded-lg border p-3">
      <div className="mb-1 flex items-center gap-2 text-sm font-medium">
        {title}
        <Badge variant={tone === "neutral" ? "secondary" : tone}>{fa(count)}</Badge>
      </div>
      {items.length > 0 && (
        <ul className="flex flex-col gap-2">
          {items.map((t, i) => (
            <li key={i} className="text-xs leading-6">
              <div className="text-sm">{t.title}</div>
              {t.reason && <div className="text-muted-foreground">{t.reason}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function capabilityTitle(key: string, outline: SpecOutline | null): string {
  return outline?.capabilities.find((c) => c.key === key)?.title ?? key;
}

/** Review before activation: a summary for CREATE, a diff with tests and risk for MODIFY. */
export function ReviewCard({
  kind,
  diff,
  approval,
  requirements,
  outline,
  report,
  decision,
  busy,
  onApprove,
  onReject,
}: ReviewCardProps) {
  const canApprove = approval?.can_approve ?? false;
  const pending = decision === "pending";
  const blockedReason =
    approval && !approval.can_approve ? approval.blocked_reason || "تأیید این نسخه فعلاً ممکن نیست." : null;

  return (
    <Card className="overflow-hidden border-primary/25 bg-primary/[.025] shadow-sm">
      <CardHeader className="flex-row flex-wrap items-center gap-2 border-b border-primary/10 bg-primary/5">
        <CardTitle>{kind === "modify" ? "بازبینی تغییر پیش از انتشار" : "بازبینی ربات پیش از انتشار"}</CardTitle>
        {diff && (
          <Badge variant={RISK_VARIANT[diff.risk]} className="ms-auto">
            {RISK_LABELS[diff.risk]}
          </Badge>
        )}
        {decision === "approved" && <Badge variant="success" className="ms-auto">تأیید شد</Badge>}
        {decision === "rejected" && <Badge variant="secondary" className="ms-auto">رد شد</Badge>}
      </CardHeader>

      <CardContent className="flex flex-col gap-6">
        {diff ? (
          <>
            <section>
              <h4 className="mb-2 text-sm font-semibold">تغییرها</h4>
              {diff.changes.length === 0 ? (
                <p className="text-sm text-muted-foreground">تغییری در مشخصات ربات وجود ندارد.</p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {diff.changes.map((c, i) => {
                    const Icon = CHANGE_ICON[c.kind];
                    return (
                      <li key={i} className="flex items-center gap-3 rounded-xl border border-border/70 bg-card p-3 text-sm">
                        <span className={`flex size-5 shrink-0 items-center justify-center rounded ${CHANGE_STYLE[c.kind]}`}>
                          <Icon className="size-3.5" />
                        </span>
                        <span>{c.label_fa}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {diff.requirements && <RequirementsDelta delta={diff.requirements} />}

            {diff.affected_capabilities.length > 0 && (
              <section>
                <h4 className="mb-2 text-sm font-semibold">قابلیت‌های تحت‌تأثیر</h4>
                <div className="flex flex-wrap gap-2">
                  {diff.affected_capabilities.map((key) => (
                    <Badge key={key} variant="accent" className="gap-2">
                      {capabilityTitle(key, outline)}
                      <span dir="ltr" className="font-mono text-[10px] opacity-70">
                        {key}
                      </span>
                    </Badge>
                  ))}
                </div>
              </section>
            )}

            <section>
              <h4 className="mb-2 text-sm font-semibold">آزمون‌ها</h4>
              <div className="grid gap-2 sm:grid-cols-3">
                <TestGroupBlock title="منتقل‌شده" group={diff.tests.carried} tone="neutral" />
                <TestGroupBlock title="جدید" group={diff.tests.new} tone="success" />
                <TestGroupBlock title="کنار گذاشته‌شده" group={diff.tests.superseded} tone="warning" />
              </div>
              {report && (
                <p className="mt-2 text-xs text-muted-foreground">
                  نتیجهٔ نهایی: {fa(report.passed)} از {fa(report.total)} آزمون موفق
                </p>
              )}
            </section>

            {diff.warnings.length > 0 && (
              <section className="rounded-lg border border-warning/30 bg-warning/5 p-3">
                <h4 className="mb-1.5 flex items-center gap-2 text-sm font-semibold">
                  <TriangleAlert className="size-4 text-warning" />
                  هشدارها
                </h4>
                <ul className="flex flex-col gap-1 text-sm leading-7">
                  {diff.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
        ) : (
          <CreateSummary requirements={requirements} outline={outline} report={report} />
        )}

        {blockedReason && pending && (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm leading-7">
            <TriangleAlert className="mt-1 size-4 shrink-0 text-destructive" />
            <div>
              <div className="font-medium">تأیید ممکن نیست</div>
              <div>{blockedReason}</div>
            </div>
          </div>
        )}
      </CardContent>

      {pending && approval && (
        <CardFooter className="flex flex-wrap gap-2 border-t border-primary/10 bg-primary/5">
          <Button onPress={onApprove} isDisabled={!canApprove || busy}>
            <Check />
            تأیید و فعال‌سازی
          </Button>
          <Button variant="outline" onPress={onReject} isDisabled={busy}>
            <X />
            رد کردن
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}

/** "What changed in the requirements": added, changed (before and after) and removed statements. */
function RequirementsDelta({ delta }: { delta: NonNullable<EventPayloads["diff"]["requirements"]> }) {
  const added = delta.added ?? [];
  const changed = delta.changed ?? [];
  const removed = delta.removed ?? [];
  if (added.length + changed.length + removed.length === 0) return null;
  const idLabel = (id: string) => id.replace(/\d+/, (d) => fa(d));
  return (
    <section aria-label="تغییر نیازمندی‌ها">
      <h4 className="mb-2 text-sm font-semibold">چه چیزی در نیازمندی‌ها تغییر کرد</h4>
      <ul className="flex flex-col gap-1.5">
        {added.map((r) => (
          <li key={`a-${r.id}`} className={`flex items-start gap-2 rounded-md border p-2 text-sm leading-7 ${CHANGE_STYLE.added}`}>
            <Plus className="mt-1.5 size-3.5 shrink-0" aria-label="افزوده شد" />
            <span>
              <span className="text-xs opacity-70">{idLabel(r.id)}</span> {r.statement}
            </span>
          </li>
        ))}
        {changed.map((r) => (
          <li key={`c-${r.id}`} className={`flex items-start gap-2 rounded-md border p-2 text-sm leading-7 ${CHANGE_STYLE.changed}`}>
            <Pencil className="mt-1.5 size-3.5 shrink-0" aria-label="تغییر کرد" />
            <span className="flex flex-col">
              <span className="text-xs opacity-70">{idLabel(r.id)}</span>
              <span>
                <span className="text-xs">قبل: </span>
                <del className="opacity-80">{r.before}</del>
              </span>
              <span>
                <span className="text-xs">بعد: </span>
                {r.after}
              </span>
            </span>
          </li>
        ))}
        {removed.map((r) => (
          <li key={`r-${r.id}`} className={`flex items-start gap-2 rounded-md border p-2 text-sm leading-7 ${CHANGE_STYLE.removed}`}>
            <Minus className="mt-1.5 size-3.5 shrink-0" aria-label="حذف شد" />
            <span>
              <span className="text-xs opacity-70">{idLabel(r.id)}</span> <del>{r.statement}</del>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CreateSummary({
  requirements,
  outline,
  report,
}: {
  requirements: Requirements | null;
  outline: SpecOutline | null;
  report: TestReportPayload | null;
}) {
  const confirmed = requirements?.items.filter((r) => r.status === "confirmed").length ?? 0;
  const assumed = requirements?.items.filter((r) => r.status === "assumed").length ?? 0;
  const unsupported = requirements?.unsupported.length ?? 0;
  return (
    <div className="flex flex-col gap-4">
      {requirements && (
        <section>
          <h4 className="mb-1 text-sm font-semibold">نیازمندی‌ها</h4>
          <p className="text-sm leading-7">
            {fa(confirmed)} مورد تأییدشده و {fa(assumed)} مورد فرض‌شده
            {unsupported > 0 && `؛ ${fa(unsupported)} مورد پشتیبانی نمی‌شود`}.
          </p>
        </section>
      )}
      {outline && (
        <section>
          <h4 className="mb-2 text-sm font-semibold">قابلیت‌های ساخته‌شده</h4>
          <ul className="flex flex-col gap-1.5">
            {outline.capabilities.map((c) => (
              <li key={c.key} className="flex items-center gap-2 text-sm">
                <Badge variant="accent">{CAPABILITY_TYPE_LABELS[c.type]}</Badge>
                <span>{c.title}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            منوی ربات: {outline.menu.map((m) => m.label).join("، ")}
          </p>
        </section>
      )}
      {report && (
        <section>
          <h4 className="mb-1 text-sm font-semibold">آزمون‌ها</h4>
          <p className="text-sm">
            {fa(report.passed)} از {fa(report.total)} آزمون موفق
          </p>
        </section>
      )}
      <p className="text-xs leading-6 text-muted-foreground">
        پیش از تأیید می‌توانید ربات را در تب «شبیه‌ساز» امتحان کنید. با تأیید، این نسخه فعال می‌شود.
      </p>
    </div>
  );
}
