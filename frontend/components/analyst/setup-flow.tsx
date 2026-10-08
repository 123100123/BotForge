"use client";

import { ArrowLeftIcon, Loader2Icon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import type { AnalysisProfileOut, AnalysisRunOut, UploadOut } from "@/lib/types";
import { AssistantLimit, isDailyCap } from "./assistant-limit";
import { InspectionView } from "./inspection-view";
import { ProfileBuilder } from "./profile-builder";
import { ProfileEditDialog } from "./profile-edit-dialog";
import { ProfileSummary } from "./profile-summary";
import { RunReport } from "./run-report";
import { SetupStepper } from "./setup-stepper";
import { UploadZone } from "./upload-zone";

type Step = 1 | 2 | 3 | 4;

function StepPanel({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section aria-labelledby="setup-step-title" className="flex flex-col gap-5 rounded-md border border-border bg-surface p-5 sm:p-6">
      <div className="flex flex-col gap-1">
        <h2 id="setup-step-title" className="text-h2 text-fg">
          {title}
        </h2>
        {hint && <p className="text-small text-fg-secondary">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

/**
 * The first analysis, as four steps that really happen in this order: file, structure, analysis profile,
 * report. It stays mounted until the owner leaves it, even after the profile exists (so the report is the last
 * step, not a jump to another screen).
 */
export function SetupFlow({
  botId,
  uploads,
  onUploaded,
  onProfile,
  runProfile,
  onFinish,
}: {
  botId: string;
  uploads: UploadOut[];
  /** A file was stored (new or reused): add it to the page's list. */
  onUploaded: (upload: UploadOut) => void;
  /** A profile was created or changed: add or replace it in the page's list. */
  onProfile: (profile: AnalysisProfileOut) => void;
  runProfile: (profile: AnalysisProfileOut, uploadId: string, narrative: boolean) => Promise<AnalysisRunOut>;
  onFinish: (run: AnalysisRunOut | null) => void;
}) {
  const [step, setStep] = useState<Step>(1);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [profile, setProfile] = useState<AnalysisProfileOut | null>(null);
  const [run, setRun] = useState<AnalysisRunOut | null>(null);
  const [editing, setEditing] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<{ message: string; cap: boolean } | null>(null);
  const [dailyBusy, setDailyBusy] = useState(false);
  const upload = uploads.find((u) => u.id === uploadId) ?? null;

  function pick(u: UploadOut) {
    onUploaded(u);
    setUploadId(u.id);
    setProfile(null);
    setStep(2);
  }

  async function execute(p: AnalysisProfileOut, id: string) {
    setRunning(true);
    setError(null);
    setStep(4);
    try {
      setRun(await runProfile(p, id, true));
    } catch (err) {
      setError({ message: errorMessage(err), cap: isDailyCap(err) });
    } finally {
      setRunning(false);
    }
  }

  async function toggleDaily(on: boolean) {
    if (!profile) return;
    setDailyBusy(true);
    try {
      const saved = await api.updateAnalysisProfile(botId, profile.id, { daily_report: on });
      setProfile(saved);
      onProfile(saved);
    } catch (err) {
      setError({ message: errorMessage(err), cap: false });
    } finally {
      setDailyBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <SetupStepper current={step} />

      {step === 1 && (
        <StepPanel title="فایل اکسل را بارگذاری کنید" hint="یک فایل نمونه از گزارش روزانه یا هفتگی‌تان بدهید؛ از روی آن ساختار جدول را می‌خوانیم.">
          <UploadZone botId={botId} onUploaded={pick} />
          {uploads.length > 0 && (
            <div className="flex max-w-md flex-col gap-1.5">
              <Label htmlFor="setup-earlier">یا یکی از فایل‌های قبلی را انتخاب کنید</Label>
              <Select
                id="setup-earlier"
                value=""
                onChange={(e) => {
                  const u = uploads.find((x) => x.id === e.target.value);
                  if (u) pick(u);
                }}
              >
                <option value="">انتخاب فایل…</option>
                {uploads.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.filename} · {formatDateTime(u.created_at)}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </StepPanel>
      )}

      {step === 2 && upload && (
        <StepPanel title="ساختار فایل" hint="این چیزی است که از فایل خوانده شد: ستون‌ها، نوع داده‌شان و چند نمونه. معنی ستون‌ها را شما می‌دانید؛ در مرحلهٔ بعد دستیار بر اساس آن‌ها پیشنهاد می‌دهد.">
          <InspectionView upload={upload} />
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => setStep(3)}>
              ادامه: پروفایل تحلیل
              <ArrowLeftIcon aria-hidden className="rtl:-scale-x-100" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setUploadId(null);
                setStep(1);
              }}
            >
              انتخاب فایل دیگر
            </Button>
          </div>
        </StepPanel>
      )}

      {step === 3 && upload && (
        <StepPanel
          title="پروفایل تحلیل"
          hint={profile ? "این پیشنهاد دستیار است. اگر چیزی را نمی‌خواهید، ویرایش کنید؛ بعد تأیید کنید تا گزارش ساخته شود." : "دستیار از روی ستون‌ها پیشنهاد می‌دهد چه چیزی اندازه‌گیری و بررسی شود."}
        >
          {!profile ? (
            <>
              <ProfileBuilder
                botId={botId}
                uploadId={upload.id}
                onCreated={(p) => {
                  setProfile(p);
                  onProfile(p);
                }}
                onLate={onProfile}
              />
              <div>
                <Button type="button" variant="ghost" size="sm" onClick={() => setStep(2)}>
                  بازگشت به ساختار فایل
                </Button>
              </div>
            </>
          ) : (
            <>
              <ProfileSummary profile={profile}>
                <div className="flex flex-col gap-3 border-t border-border pt-5">
                  <p className="text-body text-fg">این پروفایل برای فایل‌های بعدی با همین ساختار دوباره استفاده می‌شود.</p>
                  <div className="flex items-start gap-3">
                    <Switch id="setup-daily" checked={profile.daily_report} onCheckedChange={(on) => void toggleDaily(on)} disabled={dailyBusy} className="mt-1" />
                    <div className="flex flex-col gap-0.5">
                      <Label htmlFor="setup-daily">گزارش روزانهٔ کارکنان</Label>
                      <p className="text-caption text-fg-muted">فایل‌هایی که کارکنان هر روز در تلگرام می‌فرستند با همین پروفایل تحلیل می‌شود.</p>
                    </div>
                  </div>
                </div>
              </ProfileSummary>
              {error && !running && <ErrorNote>{error.message}</ErrorNote>}
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => void execute(profile, upload.id)}>
                  تأیید و ساخت گزارش
                </Button>
                <Button type="button" variant="secondary" onClick={() => setEditing(true)}>
                  ویرایش پروفایل
                </Button>
              </div>
              {editing && (
                <ProfileEditDialog
                  botId={botId}
                  profile={profile}
                  onClose={() => setEditing(false)}
                  onSaved={(p) => {
                    setEditing(false);
                    setProfile(p);
                    onProfile(p);
                  }}
                />
              )}
            </>
          )}
        </StepPanel>
      )}

      {step === 4 && (
        <div className="flex flex-col gap-4">
          {running && (
            <div role="status" className="flex items-center gap-3 rounded-md border border-border bg-surface p-5 text-body text-fg">
              <Loader2Icon aria-hidden className="size-5 animate-spin text-brand-text" strokeWidth={1.75} />
              در حال تحلیل فایل و ساخت گزارش…
            </div>
          )}
          {!running && error && (
            <StepPanel title="گزارش ساخته نشد">
              {error.cap ? <AssistantLimit /> : <ErrorNote>{error.message}</ErrorNote>}
              <div className="flex flex-wrap gap-2">
                {profile && upload && (
                  <Button type="button" onClick={() => void execute(profile, upload.id)}>
                    تلاش دوباره
                  </Button>
                )}
                <Button type="button" variant="secondary" onClick={() => setStep(3)}>
                  بازگشت به پروفایل
                </Button>
              </div>
            </StepPanel>
          )}
          {!running && run && (
            <>
              <RunReport
                botId={botId}
                run={run}
                profile={profile}
                onProfileCreated={(p) => {
                  onProfile(p);
                  setProfile(p);
                  setRun(null);
                  setStep(3);
                }}
                onRetry={async (r) => {
                  if (profile && r.upload_id) setRun(await runProfile(profile, r.upload_id, true));
                }}
              />
              <div>
                <Button type="button" onClick={() => onFinish(run)}>
                  رفتن به فهرست تحلیل‌ها
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
