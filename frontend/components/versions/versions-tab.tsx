"use client";

import { useEffect, useState } from "react";
import { History, Undo2 } from "lucide-react";
import type { WorkspaceTab } from "@/components/agent/agent-tab";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { REVISION_STATUS_LABELS, REVISION_STATUS_VARIANTS } from "@/components/app/revision-labels";
import { EmptyState, ErrorNote, InfoNote, LoadingBlock } from "@/components/app/state-blocks";
import { useRevisions } from "@/components/app/use-revisions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import type { Bot, RevisionDetail } from "@/lib/types";
import { RevisionList } from "./revision-list";
import { SpecDiff } from "./spec-diff";

export function VersionsTab({
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
          <Button variant="outline" onClick={() => onOpenTab("agent")}>
            رفتن به تب ایجنت
          </Button>
        }
      >
        هر بار که ربات ساخته یا تغییر داده شود، یک نسخهٔ جدید اینجا ثبت می‌شود و می‌توانید تغییرات را ببینید یا به نسخهٔ قبل برگردید.
      </EmptyState>
    );
  }

  const shown = detail && detail.id === selectedId ? detail : null;

  return (
    <div className="grid gap-5 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] md:items-start">
      <RevisionList
        revisions={revisions}
        selectedId={selectedId}
        onSelect={(id) => {
          setPickedId(id);
          setDone(null);
        }}
      />

      <div className="flex flex-col gap-3">
        {done && <InfoNote>{done}</InfoNote>}
        {detailError && <ErrorNote>{detailError}</ErrorNote>}
        {!shown && !detailError && <LoadingBlock />}
        {shown && (
          <Card>
            <CardHeader className="gap-2">
              <CardTitle className="flex flex-wrap items-center gap-2 text-base">
                <History className="size-5 text-muted-foreground" />
                نسخهٔ {fa(shown.number)}
                <Badge variant={REVISION_STATUS_VARIANTS[shown.status]}>{REVISION_STATUS_LABELS[shown.status]}</Badge>
                {shown.status === "superseded" && (
                  <Button variant="outline" size="sm" className="ms-auto" onClick={() => setRollbackOpen(true)}>
                    <Undo2 />
                    بازگشت به این نسخه
                  </Button>
                )}
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                ساخته‌شده در {formatDateTime(shown.created_at)}
                {shown.activated_at && ` - فعال‌شده در ${formatDateTime(shown.activated_at)}`}
              </p>
              {shown.change_request && <p className="rounded-md bg-muted/60 p-3 text-sm leading-7">{shown.change_request}</p>}
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
