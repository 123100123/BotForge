"use client";

import { useEffect, useState } from "react";
import { GitCompareArrows, History, Undo2 } from "lucide-react";
import type { WorkspaceTab } from "@/components/app/workspace";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { REVISION_STATUS_LABELS, REVISION_STATUS_VARIANTS } from "@/components/app/revision-labels";
import { EmptyState, ErrorNote, InfoNote, LoadingBlock } from "@/components/app/state-blocks";
import { Segmented } from "@/components/app/segmented";
import { useRevisions } from "@/components/app/use-revisions";
import { TestsTab } from "@/components/tests/tests-tab";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import type { Bot, RevisionDetail } from "@/lib/types";
import { RevisionList } from "./revision-list";
import { SpecDiff } from "./spec-diff";

type VersionsView = "history" | "tests";

/** Versions section: the revision history, with the scenario tests as a sub-section. */
export function VersionsTab({
  bot,
  onBotChanged,
  onOpenTab,
}: {
  bot: Bot;
  onBotChanged: () => void;
  onOpenTab: (tab: WorkspaceTab) => void;
}) {
  const [view, setView] = useState<VersionsView>("history");

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="flex flex-col justify-between gap-4 rounded-[1.5rem] border border-border/70 bg-card p-5 shadow-sm sm:flex-row sm:items-end sm:p-6">
        <div><span className="mb-3 inline-grid size-11 place-items-center rounded-2xl bg-primary/10 text-primary"><History className="size-6" /></span><h2 className="text-xl font-bold">نسخه‌ها و آزمون‌ها</h2><p className="mt-1 text-sm leading-7 text-muted-foreground">تغییرات ربات را بررسی و هر نسخه را پیش از فعال‌سازی ارزیابی کنید.</p></div>
      <Segmented<VersionsView>
        label="بخش نسخه‌ها"
        value={view}
        onChange={setView}
        options={[
          { value: "history", label: "تاریخچه" },
          { value: "tests", label: "آزمون‌ها" },
        ]}
      />
      </header>
      {view === "history" ? (
        <RevisionHistory bot={bot} onBotChanged={onBotChanged} onOpenTab={onOpenTab} />
      ) : (
        <TestsTab bot={bot} onOpenTab={onOpenTab} />
      )}
    </div>
  );
}

function RevisionHistory({
  bot,
  onBotChanged,
  onOpenTab,
}: {
  bot: Bot;
  onBotChanged: () => void;
  onOpenTab: (tab: WorkspaceTab) => void;
}) {
  const { revisions, error: loadError, reload } = useRevisions(bot.id, bot.active_revision_id);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RevisionDetail | null>(null);
  const [loadedError, setLoadedError] = useState<{ id: string; message: string } | null>(null);
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  /** Bumped after a rollback so the selected revision's detail is read again. */
  const [detailTick, setDetailTick] = useState(0);

  // Default: the newest revision.
  const selectedId = pickedId ?? revisions?.[0]?.id ?? null;

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    api.getRevision(selectedId).then(
      (d) => {
        if (cancelled) return;
        setDetail(d);
        setLoadedError(null);
      },
      (err) => !cancelled && setLoadedError({ id: selectedId, message: errorMessage(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [selectedId, detailTick]);

  const detailError = loadedError && loadedError.id === selectedId ? loadedError.message : null;

  if (loadError) return <ErrorNote>{loadError}</ErrorNote>;
  if (!revisions) return <LoadingBlock />;
  if (revisions.length === 0) {
    return (
      <EmptyState
        title="هنوز نسخه‌ای وجود ندارد"
        action={
          <Button variant="outline" onPress={() => onOpenTab("agent")}>
            رفتن به بخش دستیار هوشمند
          </Button>
        }
      >
        هر بار که ربات ساخته یا تغییر داده شود، یک نسخهٔ جدید اینجا ثبت می‌شود و می‌توانید تغییرات را ببینید یا به نسخهٔ قبل برگردید.
      </EmptyState>
    );
  }

  const shown = detail && detail.id === selectedId ? detail : null;

  return (
    <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,19rem)_minmax(0,1fr)] xl:items-start">
      <RevisionList
        revisions={revisions}
        selectedId={selectedId}
        onSelect={(id) => {
          setPickedId(id);
          setDone(null);
        }}
      />

      <div className="flex min-w-0 flex-col gap-3">
        {done && <InfoNote>{done}</InfoNote>}
        {detailError && <ErrorNote>{detailError}</ErrorNote>}
        {!shown && !detailError && <LoadingBlock />}
        {shown && (
          <Card className="overflow-hidden">
            <CardHeader className="gap-2">
              <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                <GitCompareArrows className="size-5 text-primary" />
                نسخهٔ {fa(shown.number)}
                <Badge variant={REVISION_STATUS_VARIANTS[shown.status]}>{REVISION_STATUS_LABELS[shown.status]}</Badge>
                {shown.status === "superseded" && (
                  <Button variant="outline" size="sm" className="ms-auto" onPress={() => setRollbackOpen(true)}>
                    <Undo2 />
                    بازگشت به این نسخه
                  </Button>
                )}
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                ساخته‌شده در {formatDateTime(shown.created_at)}
                {shown.activated_at && ` - فعال‌شده در ${formatDateTime(shown.activated_at)}`}
              </p>
              {shown.change_request && <p className="rounded-md bg-surface-secondary/60 p-3 text-sm leading-7">{shown.change_request}</p>}
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <h4 className="text-sm font-semibold">تغییرات نسبت به نسخهٔ قبل</h4>
              <SpecDiff diff={shown.diff} isFirst={shown.parent_id === null} />
            </CardContent>
          </Card>
        )}
      </div>

      {shown && (
        <ConfirmDialog
          open={rollbackOpen}
          onOpenChange={setRollbackOpen}
          title={`بازگشت به نسخهٔ ${fa(shown.number)}`}
          description="این نسخه دوباره فعال می‌شود و ربات تلگرام از همین حالا مطابق آن رفتار می‌کند. گفتگوهای در جریان مشتری‌ها از اول شروع می‌شود. داده‌های شما تغییر نمی‌کند."
          confirmLabel="بازگشت به این نسخه"
          onConfirm={async () => {
            await api.activateRevision(shown.id);
            setDone(`نسخهٔ ${fa(shown.number)} دوباره فعال شد.`);
            setDetailTick((t) => t + 1);
            reload();
            onBotChanged();
          }}
        />
      )}
    </div>
  );
}
