"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleCheck, CircleX, Play } from "lucide-react";
import type { WorkspaceTab } from "@/components/app/workspace";
import { defaultRevision, revisionOptionLabel } from "@/components/app/revision-labels";
import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { useRevisions } from "@/components/app/use-revisions";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { Bot, RevisionDetail, ScenarioResult } from "@/lib/types";
import { ScenarioDetail } from "./scenario-detail";
import { ScenarioList } from "./scenario-list";

function firstScenarioId(d: RevisionDetail): string | null {
  return d.test_report?.results?.find((r) => !r.passed)?.scenario_id ?? d.scenarios?.[0]?.id ?? null;
}

export function TestsTab({ bot, onOpenTab }: { bot: Bot; onOpenTab: (tab: WorkspaceTab) => void }) {
  const { revisions, error: loadError, reload } = useRevisions(bot.id, bot.active_revision_id);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<RevisionDetail | null>(null);
  const [loadedError, setLoadedError] = useState<{ id: string; message: string } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Default: the draft under review if there is one, otherwise the active revision.
  const revisionId = pickedId ?? (revisions ? (defaultRevision(revisions)?.id ?? null) : null);

  useEffect(() => {
    if (!revisionId) return;
    let cancelled = false;
    api.getRevision(revisionId).then(
      (d) => {
        if (cancelled) return;
        setLoaded(d);
        setLoadedError(null);
        // Open on the first failing scenario, otherwise the first one.
        setSelectedId(firstScenarioId(d));
      },
      (err) => !cancelled && setLoadedError({ id: revisionId, message: errorMessage(err) }),
    );
    return () => {
      cancelled = true;
    };
  }, [revisionId]);

  // A detail that belongs to a previously selected revision counts as "still loading".
  const detail = loaded && loaded.id === revisionId ? loaded : null;
  const detailError = loadedError && loadedError.id === revisionId ? loadedError.message : null;

  const results = useMemo(() => {
    const map: Record<string, ScenarioResult> = {};
    for (const r of detail?.test_report?.results ?? []) map[r.scenario_id] = r;
    return map;
  }, [detail]);

  async function runAgain() {
    if (!detail || running) return;
    setRunning(true);
    setRunError(null);
    try {
      const report = await api.runRevisionTests(detail.id);
      // The backend derives scenarios when none are stored, so read the revision again.
      try {
        const fresh = await api.getRevision(detail.id);
        setLoaded({ ...fresh, test_report: fresh.test_report ?? report });
        setSelectedId(firstScenarioId(fresh));
      } catch {
        setLoaded({ ...detail, test_report: report });
      }
      void reload();
    } catch (err) {
      setRunError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  if (loadError) return <ErrorNote>{loadError}</ErrorNote>;
  if (!revisions) return <LoadingBlock />;
  if (revisions.length === 0) {
    return (
      <EmptyState
        title="هنوز آزمونی وجود ندارد"
        action={
          <Button variant="outline" onClick={() => onOpenTab("agent")}>
            رفتن به تب ایجنت
          </Button>
        }
      >
        وقتی ربات ساخته شود، آزمون‌های آن به‌صورت جمله‌های فارسی اینجا نمایش داده می‌شود.
      </EmptyState>
    );
  }

  const report = detail?.test_report ?? null;
  const allPassed = report !== null && report.failed === 0;
  const scenarios = detail?.scenarios ?? [];
  const selected = scenarios.find((s) => s.id === selectedId) ?? null;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid min-w-56 gap-1.5">
          <Label htmlFor="tests-revision">نسخه</Label>
          <Select id="tests-revision" value={revisionId ?? ""} onChange={(e) => {
              setPickedId(e.target.value);
              setRunError(null);
            }}>
            {revisions.map((r) => (
              <option key={r.id} value={r.id}>
                {revisionOptionLabel(r)}
              </option>
            ))}
          </Select>
        </div>
        <Button variant="outline" onClick={runAgain} disabled={!detail || running}>
          <Play />
          {running ? "در حال اجرا…" : scenarios.length === 0 ? "اجرای آزمون" : "اجرای دوباره"}
        </Button>
      </div>

      {runError && <ErrorNote>{runError}</ErrorNote>}
      {detailError && <ErrorNote>{detailError}</ErrorNote>}
      {!detail && !detailError && <LoadingBlock />}

      {detail && (
        <>
          <Card className={report ? (allPassed ? "border-success/40" : "border-destructive/40") : undefined}>
            <CardContent className="flex items-center gap-2 text-lg font-semibold">
              {report ? (
                <>
                  {allPassed ? <CircleCheck className="size-5 text-success-text" /> : <CircleX className="size-5 text-danger-text" />}
                  <span>
                    {fa(report.passed)} از {fa(report.total)} سناریو موفق
                  </span>
                </>
              ) : (
                <span className="text-base font-normal text-muted-foreground">برای این نسخه هنوز آزمونی اجرا نشده است.</span>
              )}
            </CardContent>
          </Card>

          {scenarios.length === 0 && (
            <EmptyState
              title="برای این نسخه سناریوی آزمونی ذخیره نشده است"
              action={
                <Button onClick={runAgain} disabled={running}>
                  <Play />
                  {running ? "در حال اجرا…" : "اجرای آزمون"}
                </Button>
              }
            >
              با اجرای آزمون، سناریوها از روی مشخصات همین نسخه ساخته و اجرا می‌شود و نتیجه اینجا نمایش داده می‌شود.
            </EmptyState>
          )}

          {scenarios.length > 0 && (
            <div className="grid gap-5 md:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] md:items-start">
              <Card className="py-3">
                <CardContent className="px-2">
                  <ScenarioList scenarios={scenarios} results={results} selectedId={selectedId} onSelect={setSelectedId} />
                </CardContent>
              </Card>
              {selected && (
                <ScenarioDetail
                  key={selected.id}
                  scenario={selected}
                  result={results[selected.id]}
                  requirements={detail.requirements?.items ?? []}
                />
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
