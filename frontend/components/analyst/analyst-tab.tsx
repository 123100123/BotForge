"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeftIcon, FileSpreadsheetIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { InfoNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { AnalysisProfileOut, AnalysisRunOut, Bot, UploadOut } from "@/lib/types";
import { ProfileEditDialog } from "./profile-edit-dialog";
import { ProfileList } from "./profile-list";
import { RunDialog } from "./run-dialog";
import { RunHistory } from "./run-history";
import { RunReport } from "./run-report";
import { SetupFlow } from "./setup-flow";

interface AnalystData {
  uploads: UploadOut[];
  profiles: AnalysisProfileOut[];
  runs: AnalysisRunOut[];
}

/** Insert or replace by id, newest first. */
function upsert<T extends { id: string }>(list: T[], item: T): T[] {
  return [item, ...list.filter((x) => x.id !== item.id)];
}

/**
 * Spreadsheet analysis (تحلیل فایل اکسل). Until a profile exists it is the four-step setup; after that it is
 * the list of profiles, a way to run one on a file, and the history of runs. A run is a page of its own
 * (`?run=<id>`), so it can be linked.
 */
export function AnalystTab({ bot }: { bot: Bot }) {
  return <AnalystScreen key={bot.id} botId={bot.id} />;
}

function AnalystSkeleton() {
  return (
    <div role="status" aria-label="در حال بارگذاری" className="flex flex-col gap-4">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-28 w-full" />
    </div>
  );
}

function AnalystScreen({ botId }: { botId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const runId = useSearchParams().get("run");
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<AnalystData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [setup, setSetup] = useState<boolean | null>(null);
  const [runFor, setRunFor] = useState<{ profileId?: string } | null>(null);
  const [editing, setEditing] = useState<AnalysisProfileOut | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listUploads(botId), api.listAnalysisProfiles(botId), api.listAnalysisRuns(botId)]).then(
      ([uploads, profiles, runs]) => {
        if (cancelled) return;
        setError(null);
        setData({ uploads: uploads ?? [], profiles: profiles ?? [], runs: runs ?? [] });
        setSetup((s) => s ?? (profiles ?? []).length === 0);
      },
      (err) => {
        if (!cancelled) setError(errorMessage(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [botId, attempt]);

  // A run page starts at its top.
  useEffect(() => {
    if (runId) window.scrollTo?.({ top: 0 });
  }, [runId]);

  const patch = useCallback((fn: (d: AnalystData) => AnalystData) => setData((d) => (d ? fn(d) : d)), []);
  const onUploaded = useCallback((u: UploadOut) => patch((d) => ({ ...d, uploads: upsert(d.uploads, u) })), [patch]);
  const onProfile = useCallback((p: AnalysisProfileOut) => patch((d) => ({ ...d, profiles: upsert(d.profiles, p) })), [patch]);

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data || setup === null) return <AnalystSkeleton />;

  const { uploads, profiles, runs } = data;
  const runHref = (run: AnalysisRunOut) => `${pathname}?run=${encodeURIComponent(run.id)}`;

  async function runProfile(profile: AnalysisProfileOut, uploadId: string, narrative: boolean): Promise<AnalysisRunOut> {
    const run = await api.runAnalysis(botId, profile.id, { upload_id: uploadId, narrative });
    patch((d) => ({ ...d, runs: upsert(d.runs, run) }));
    // The run count lives on the server; a failed refresh only leaves the old count visible.
    api.listAnalysisProfiles(botId).then(
      (fresh) => patch((d) => ({ ...d, profiles: fresh ?? d.profiles })),
      () => {},
    );
    return run;
  }

  if (setup) {
    return (
      <SetupFlow
        botId={botId}
        uploads={uploads}
        onUploaded={onUploaded}
        onProfile={onProfile}
        runProfile={runProfile}
        onFinish={() => {
          setSetup(false);
          router.replace(pathname);
        }}
      />
    );
  }

  const editDialog = editing && (
    <ProfileEditDialog
      botId={botId}
      profile={editing}
      onClose={() => setEditing(null)}
      onSaved={(p) => {
        onProfile(p);
        setEditing(null);
      }}
    />
  );
  const profileOf = (run: AnalysisRunOut) => profiles.find((p) => p.id === run.profile_id) ?? null;

  // One run, as a page.
  if (runId) {
    const run = runs.find((r) => r.id === runId);
    return (
      <div className="flex flex-col gap-4">
        <Link href={pathname} className="inline-flex w-fit items-center gap-1.5 rounded-xs text-small text-brand-text hover:underline">
          <ArrowLeftIcon aria-hidden className="size-4 rtl:-scale-x-100" strokeWidth={1.75} />
          همهٔ تحلیل‌ها
        </Link>
        {run ? (
          <RunReport
            key={run.id}
            botId={botId}
            run={run}
            profile={profileOf(run)}
            onProfileCreated={(profile, intent) => {
              onProfile(profile);
              setNotice(
                intent === "update"
                  ? `نسخهٔ به‌روز «${profile.name}» ساخته شد. می‌توانید آن را ویرایش کنید و بعد با «اجرای تحلیل» روی فایل اجرا کنید.`
                  : `پروفایل تازهٔ «${profile.name}» ساخته شد. حالا می‌توانید با «اجرای تحلیل» آن را روی فایل اجرا کنید.`,
              );
              if (intent === "update") setEditing(profile);
              router.push(pathname);
            }}
            onRetry={async (r) => {
              const profile = profileOf(r);
              if (!profile || !r.upload_id) return;
              const next = await runProfile(profile, r.upload_id, true);
              router.replace(runHref(next));
            }}
          />
        ) : (
          <EmptyState
            icon={<FileSpreadsheetIcon />}
            title="این تحلیل پیدا نشد"
            description="ممکن است حذف شده باشد. از فهرست تحلیل‌ها یکی دیگر را باز کنید."
            action={
              <Button variant="secondary" asChild>
                <Link href={pathname}>رفتن به فهرست تحلیل‌ها</Link>
              </Button>
            }
          />
        )}
        {editDialog}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {notice && <InfoNote>{notice}</InfoNote>}

      <section aria-labelledby="profiles-title" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="profiles-title" className="text-h2 text-fg">
            پروفایل‌های تحلیل
            <span className="ms-1.5 text-body font-normal text-fg-muted">({fa(profiles.length)})</span>
          </h2>
          <Button type="button" variant="secondary" size="sm" onClick={() => setRunFor({})}>
            تحلیل فایل تازه
          </Button>
        </div>
        <ProfileList profiles={profiles} onRun={(p) => setRunFor({ profileId: p.id })} onEdit={setEditing} />
      </section>

      <section aria-labelledby="history-title" className="flex flex-col gap-3">
        <h2 id="history-title" className="text-h2 text-fg">
          سابقهٔ تحلیل‌ها
          {runs.length > 0 && <span className="ms-1.5 text-body font-normal text-fg-muted">({fa(runs.length)})</span>}
        </h2>
        {runs.length === 0 ? (
          <div className="rounded-md border border-border bg-surface">
            <EmptyState
              icon={<FileSpreadsheetIcon />}
              title="هنوز تحلیلی اجرا نشده است"
              description="روی «اجرای تحلیل» بزنید و یک فایل بدهید؛ نتیجه‌ها اینجا ثبت می‌شوند."
            />
          </div>
        ) : (
          <RunHistory runs={runs} profiles={profiles} hrefFor={runHref} />
        )}
      </section>

      {runFor && (
        <RunDialog
          botId={botId}
          profiles={profiles}
          uploads={uploads}
          initialProfileId={runFor.profileId}
          onUploaded={onUploaded}
          onClose={() => setRunFor(null)}
          onRun={async (profile, uploadId, narrative) => {
            const run = await runProfile(profile, uploadId, narrative);
            setRunFor(null);
            setNotice(null);
            router.push(runHref(run));
          }}
        />
      )}
      {editDialog}
    </div>
  );
}
