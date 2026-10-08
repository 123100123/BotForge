"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { EmptyState, ErrorNote, InfoNote, LoadingBlock } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { ChoiceSelect } from "@/components/data/controls";
import { PageHeader, SectionToolbar } from "@/components/app/presentation";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import type { AnalysisProfileOut, AnalysisRunOut, Bot, UploadOut } from "@/lib/types";
import { cn } from "@/lib/utils";
import { InspectionView } from "./inspection-view";
import { STATUS_LABELS, STATUS_VARIANT } from "./labels";
import { ProfileCard } from "./profile-card";
import { ProfileCreateForm } from "./profile-create-form";
import { RunResult } from "./run-result";
import { UploadZone } from "./upload-zone";

interface AnalystData {
  uploads: UploadOut[];
  profiles: AnalysisProfileOut[];
  runs: AnalysisRunOut[];
}

/** Data Analyst: upload a workbook, review its inspection, save profiles, run them and browse the runs. */
export function AnalystTab({ bot }: { bot: Bot }) {
  return <AnalystScreen key={bot.id} botId={bot.id} />;
}

function AnalystScreen({ botId }: { botId: string }) {
  const [data, setData] = useState<AnalystData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspectedId, setInspectedId] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listUploads(botId), api.listAnalysisProfiles(botId), api.listAnalysisRuns(botId)]).then(
      ([uploads, profiles, runs]) => {
        if (!cancelled) setData({ uploads: uploads ?? [], profiles: profiles ?? [], runs: runs ?? [] });
      },
      (err) => {
        if (!cancelled) setError(errorMessage(err));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);

  const patch = useCallback((fn: (d: AnalystData) => AnalystData) => setData((d) => (d ? fn(d) : d)), []);

  useEffect(() => {
    if (activeRunId) resultRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [activeRunId]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <LoadingBlock />;

  const { uploads, profiles, runs } = data;
  const inspected = uploads.find((u) => u.id === inspectedId) ?? null;
  const activeRun = runs.find((r) => r.id === activeRunId) ?? null;
  const profileOf = (run: AnalysisRunOut) => profiles.find((p) => p.id === run.profile_id) ?? null;

  function onUploaded(upload: UploadOut) {
    patch((d) => ({ ...d, uploads: [upload, ...d.uploads.filter((u) => u.id !== upload.id)] }));
    return upload;
  }

  function onProfileCreated(profile: AnalysisProfileOut) {
    patch((d) => ({ ...d, profiles: [profile, ...d.profiles] }));
    setNotice(`پروفایل «${profile.name}» ساخته شد. حالا می‌توانید با «اجرای تحلیل» آن را روی یک فایل اجرا کنید.`);
  }

  async function runProfile(profile: AnalysisProfileOut, uploadId: string, narrative: boolean) {
    const run = await api.runAnalysis(botId, profile.id, { upload_id: uploadId, narrative });
    patch((d) => ({ ...d, runs: [run, ...d.runs.filter((r) => r.id !== run.id)] }));
    setNotice(null);
    setActiveRunId(run.id);
    // The run count lives on the server; a failed refresh only leaves the old count visible.
    api.listAnalysisProfiles(botId).then(
      (fresh) => patch((d) => ({ ...d, profiles: fresh ?? d.profiles })),
      () => {},
    );
  }

  async function updateProfileFromRun(run: AnalysisRunOut, profile: AnalysisProfileOut | null) {
    if (!run.upload_id) return;
    const created = await api.createAnalysisProfile(botId, {
      upload_id: run.upload_id,
      name: profile ? `${profile.name} (به‌روز)` : undefined,
      daily_report: profile?.daily_report ?? false,
    });
    patch((d) => ({ ...d, profiles: [created, ...d.profiles] }));
    setNotice(`پروفایل جدید «${created.name}» از ساختار تازهٔ فایل ساخته شد. پروفایل قبلی دست‌نخورده ماند.`);
    setActiveRunId(null);
  }

  return (
    <div className="flex min-w-0 flex-col gap-7">
      <PageHeader eyebrow="بینش" title="تحلیل‌گر داده" description="فایل اکسل یا CSV را بارگذاری کنید؛ ساختار آن بررسی می‌شود و می‌توانید پروفایل تحلیل قابل‌استفادهٔ مجدد بسازید." />

      {notice && <InfoNote>{notice}</InfoNote>}

      <section aria-label="بارگذاری فایل" className="app-surface flex min-w-0 flex-col gap-4 p-4 sm:p-6">
        <SectionToolbar title="۱. فایل را وارد کنید" description="فایل تازه را بارگذاری کنید یا یکی از فایل‌های قبلی را برای بررسی باز کنید." />
        <UploadZone
          botId={botId}
          onUploaded={(u) => {
            onUploaded(u);
            setInspectedId(u.id);
            setNotice(null);
          }}
        />
        {uploads.length > 0 && (
          <div className="flex flex-col gap-1.5 sm:max-w-sm">
            <Label htmlFor="analyst-inspect">بررسی فایل‌های قبلی</Label>
            <ChoiceSelect id="analyst-inspect" label="بررسی فایل‌های قبلی" value={inspectedId ?? ""} onChange={(v) => setInspectedId(v || null)} placeholder="انتخاب فایل…" options={uploads.map((u) => ({ value: u.id, label: `${u.filename} — ${formatDateTime(u.created_at)}` }))} />
          </div>
        )}
      </section>

      {inspected && (
        <InspectionView upload={inspected}>
          <ProfileCreateForm botId={botId} upload={inspected} onCreated={onProfileCreated} />
        </InspectionView>
      )}

      <section aria-label="پروفایل‌های تحلیل" className="flex min-w-0 flex-col gap-4">
        <SectionToolbar title={`۲. پروفایل‌های تحلیل${profiles.length > 0 ? ` (${fa(profiles.length)})` : ""}`} description="تنظیمات تحلیل را یک بار بسازید و برای فایل‌های بعدی دوباره اجرا کنید." />
        {profiles.length === 0 ? (
          <EmptyState title="هنوز پروفایل تحلیلی ساخته نشده است">
            {uploads.length === 0
              ? "یک فایل اکسل یا CSV بارگذاری کنید تا ساختار آن بررسی شود و بتوانید از آن پروفایل بسازید."
              : "یکی از فایل‌های بارگذاری‌شده را بررسی کنید و از آن پروفایل تحلیل بسازید."}
          </EmptyState>
        ) : (
          <div className="grid min-w-0 items-start gap-4 xl:grid-cols-2">
            {profiles.map((p) => (
              <ProfileCard
                key={p.id}
                botId={botId}
                profile={p}
                uploads={uploads}
                onUploaded={onUploaded}
                onRun={runProfile}
                onSaved={(saved) => patch((d) => ({ ...d, profiles: d.profiles.map((x) => (x.id === saved.id ? saved : x)) }))}
              />
            ))}
          </div>
        )}
      </section>

      {activeRun && (
        <div ref={resultRef} className="scroll-mt-4">
          <RunResult key={activeRun.id} run={activeRun} profile={profileOf(activeRun)} onUpdateProfile={updateProfileFromRun} />
        </div>
      )}

      <section aria-label="سابقهٔ اجراها" className="flex min-w-0 flex-col gap-4">
        <SectionToolbar title={`۳. سابقهٔ اجراها${runs.length > 0 ? ` (${fa(runs.length)})` : ""}`} description="نتیجهٔ تحلیل‌های پیشین و هشدارها را دوباره باز کنید." />
        {runs.length === 0 ? (
          <EmptyState title="هنوز تحلیلی اجرا نشده است">
            بعد از ساخت پروفایل، «اجرای تحلیل» را بزنید تا نتیجه‌ها اینجا ثبت شوند.
          </EmptyState>
        ) : (
          <ul className="flex flex-col gap-2">
            {runs.map((r) => {
              const selected = r.id === activeRunId;
              return (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setActiveRunId(r.id)}
                    aria-pressed={selected}
                    className={cn(
                      "flex w-full min-w-0 flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-card px-4 py-3 text-start transition-colors outline-none hover:bg-secondary focus-visible:ring-[3px] focus-visible:ring-ring/40",
                      selected && "border-primary bg-accent/30",
                    )}
                  >
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate text-sm font-medium">
                        <bdi>{r.filename ?? "فایل حذف‌شده"}</bdi>
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {profileOf(r)?.name ?? "پروفایل حذف‌شده"} · {formatDateTime(r.created_at)}
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      {r.status === "ok" && (r.anomalies?.length ?? 0) > 0 && (
                        <Badge variant="warning">{fa(r.anomalies.length)} ناهنجاری</Badge>
                      )}
                      <Badge variant={STATUS_VARIANT[r.status] ?? "secondary"}>{STATUS_LABELS[r.status] ?? r.status}</Badge>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
