"use client";

import { useState } from "react";
import Link from "next/link";
import { FlaskConical, Play, Undo2 } from "lucide-react";
import { DeployedState } from "@/components/agent/deployed-state";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { useOpenSection } from "@/components/app/shell/use-open-section";
import { ScenarioBrowser } from "@/components/tests/scenario-browser";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import { sectionHref } from "@/lib/routes";
import type { RevisionDetail } from "@/lib/types";
import { ChangeStateBadge } from "./change-state";
import { ConfigDiff } from "./config-diff";
import { DetailSection } from "./detail-section";
import { Disclosure } from "./disclosure";
import { RequirementsList } from "./requirements-list";
import { revisionState } from "./run-model";
import { TestSummary, type TestFailure } from "./test-summary";
import { useRevisionDetail } from "./use-revision-detail";

interface VersionDetailProps {
  botId: string;
  revisionId: string;
  /** Number of the active version, for the rollback explanation. */
  activeNumber: number | null;
  /** This session just activated this version through an approval: show what to do next. */
  justActivated?: boolean;
  /** A version was activated or its tests ran: re-read the list and the business. */
  onChanged: () => void;
}

function failuresOf(detail: RevisionDetail): TestFailure[] {
  const titles = new Map((detail.scenarios ?? []).map((s) => [s.id, s.title]));
  return (detail.test_report?.results ?? [])
    .filter((r) => !r.passed)
    .map((r) => ({
      id: r.scenario_id,
      title: titles.get(r.scenario_id) ?? "آزمون",
      message: r.steps.find((s) => !s.passed)?.message ?? "این آزمون موفق نبود.",
    }));
}

/** A stored version: what was asked, what changed, how it tested, and the way back to it. */
export function VersionDetail({ botId, revisionId, activeNumber, justActivated = false, onChanged }: VersionDetailProps) {
  const openSection = useOpenSection();
  const { detail, error, loading, reload, set } = useRevisionDetail(revisionId);
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  if (loading) {
    return (
      <div role="status" aria-label="در حال بارگذاری نسخه" className="flex flex-col gap-3 rounded-md border border-border bg-surface p-5">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-20" />
        <Skeleton className="h-32" />
      </div>
    );
  }
  if (error || !detail) {
    return (
      <div className="rounded-md border border-border bg-surface">
        <ErrorState message={error ?? undefined} title="نسخه بارگذاری نشد" onRetry={reload} />
      </div>
    );
  }

  const state = revisionState(detail.status);
  const isFirst = detail.parent_id === null;
  const report = detail.test_report;
  const simulatorHref = `${sectionHref(botId, "test")}?revision=${encodeURIComponent(detail.id)}`;
  const canActivate = detail.status === "superseded" || detail.status === "draft";

  async function runTests() {
    if (!detail || running) return;
    setRunning(true);
    setRunError(null);
    try {
      const fresh = await api.runRevisionTests(detail.id);
      try {
        const reread = await api.getRevision(detail.id);
        set({ ...reread, test_report: reread.test_report ?? fresh });
      } catch {
        set({ ...detail, test_report: fresh });
      }
      onChanged();
    } catch (err) {
      setRunError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <article aria-label={`نسخهٔ ${fa(detail.number)}`} className="flex flex-col overflow-clip rounded-md border border-border bg-surface">
      <header className="flex flex-col gap-3 px-5 py-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 className="text-h2 text-fg">نسخهٔ {fa(detail.number)}</h2>
          <ChangeStateBadge state={state} />
        </div>
        <p className="text-small text-fg-muted">
          ساخته‌شده در {formatDateTime(detail.created_at)}
          {detail.activated_at && ` · فعال‌شده در ${formatDateTime(detail.activated_at)}`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {canActivate && (
            <Button onClick={() => setRollbackOpen(true)}>
              <Undo2 strokeWidth={1.75} />
              {detail.status === "draft" ? "فعال‌سازی این نسخه" : "بازگشت به این نسخه"}
            </Button>
          )}
          <Button asChild variant={canActivate ? "secondary" : "primary"}>
            <Link href={simulatorHref}>
              <FlaskConical strokeWidth={1.75} />
              آزمایش ربات
            </Link>
          </Button>
        </div>
      </header>

      {justActivated && (
        <div className="border-t border-border px-5 py-5">
          <DeployedState number={detail.number} onOpenSection={openSection} />
        </div>
      )}

      {detail.change_request && (
        <DetailSection title={isFirst ? "شرح کسب‌وکار" : "تغییر درخواستی"}>
          <p className="text-body whitespace-pre-wrap">{detail.change_request}</p>
        </DetailSection>
      )}

      <DetailSection title={isFirst ? "پیکربندی اولیه" : "تغییرات نسبت به نسخهٔ قبل"}>
        <ConfigDiff changes={detail.diff} isFirst={isFirst} />
      </DetailSection>

      <DetailSection
        title="آزمون‌ها"
        action={
          <Button variant="secondary" size="sm" onClick={runTests} loading={running}>
            <Play strokeWidth={1.75} />
            {report ? "اجرای دوباره" : "اجرای آزمون"}
          </Button>
        }
      >
        {runError && (
          <p role="alert" className="rounded-sm bg-danger-soft p-3 text-small text-danger-text">
            {runError}
          </p>
        )}
        <TestSummary
          total={report?.total ?? null}
          passed={report?.passed ?? 0}
          failed={report?.failed ?? 0}
          failures={failuresOf(detail)}
          pendingText="برای این نسخه هنوز آزمونی اجرا نشده است."
          listCount={detail.scenarios?.length}
        >
          {detail.scenarios && detail.scenarios.length > 0 ? (
            <ScenarioBrowser scenarios={detail.scenarios} report={report} requirements={detail.requirements?.items ?? []} />
          ) : undefined}
        </TestSummary>
      </DetailSection>

      {detail.requirements && (
        <div className="border-t border-border px-5 py-3">
          <Disclosure title="آنچه دستیار فهمید">
            <RequirementsList requirements={detail.requirements} />
          </Disclosure>
        </div>
      )}

      <ConfirmDialog
        open={rollbackOpen}
        onOpenChange={setRollbackOpen}
        title={detail.status === "draft" ? `فعال‌سازی نسخهٔ ${fa(detail.number)}` : `بازگشت به نسخهٔ ${fa(detail.number)}`}
        description={
          <>
            نسخهٔ {fa(detail.number)} {activeNumber !== null && `به‌جای نسخهٔ ${fa(activeNumber)} `}فعال می‌شود و ربات تلگرام از همین حالا
            مطابق آن رفتار می‌کند. گفتگوهای در جریان مشتری‌ها از اول شروع می‌شود. داده‌های شما (مثل سفارش‌ها و ثبت‌نام‌ها) تغییر
            نمی‌کند.
          </>
        }
        confirmLabel={detail.status === "draft" ? "فعال‌سازی" : "بازگشت به این نسخه"}
        onConfirm={async () => {
          await api.activateRevision(detail.id);
          toast({ title: `نسخهٔ ${fa(detail.number)} فعال شد`, tone: "success" });
          reload();
          onChanged();
        }}
      />
    </article>
  );
}
