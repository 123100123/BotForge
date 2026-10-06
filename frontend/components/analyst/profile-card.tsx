"use client";

import { useState } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import type { AnalysisProfileOut, UploadOut } from "@/lib/types";
import { ProfileEditDialog } from "./profile-edit-dialog";
import { UploadZone } from "./upload-zone";

const CHIP_LIMIT = 8;

function RunPanel({
  botId,
  profile,
  uploads,
  onUploaded,
  onRun,
}: {
  botId: string;
  profile: AnalysisProfileOut;
  uploads: UploadOut[];
  onUploaded: (upload: UploadOut) => void;
  onRun: (profile: AnalysisProfileOut, uploadId: string, narrative: boolean) => Promise<void>;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [narrative, setNarrative] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const uploadId = uploads.find((u) => u.id === chosen)?.id ?? uploads[0]?.id ?? "";

  async function run() {
    setBusy(true);
    setError(null);
    try {
      await onRun(profile, uploadId, narrative);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg bg-muted/40 p-3">
      {uploads.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`run-upload-${profile.id}`}>فایل برای تحلیل</Label>
          <Select
            id={`run-upload-${profile.id}`}
            value={uploadId}
            onChange={(e) => setChosen(e.target.value)}
            disabled={busy}
          >
            {uploads.map((u) => (
              <option key={u.id} value={u.id}>
                {u.filename} — {formatDateTime(u.created_at)}
              </option>
            ))}
          </Select>
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <span className="text-xs text-muted-foreground">
          {uploads.length > 0 ? "یا فایل تازه‌ای بارگذاری کنید:" : "برای اجرا ابتدا یک فایل بارگذاری کنید:"}
        </span>
        <UploadZone
          botId={botId}
          compact
          onUploaded={(u) => {
            setChosen(u.id);
            onUploaded(u);
          }}
        />
      </div>
      <div className="flex items-center gap-2">
        <Switch id={`run-narrative-${profile.id}`} checked={narrative} onCheckedChange={setNarrative} disabled={busy} />
        <Label htmlFor={`run-narrative-${profile.id}`}>نوشتن خلاصهٔ متنی از نتیجه</Label>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Button type="button" onClick={() => void run()} disabled={busy || !uploadId} className="w-full sm:w-fit">
        {busy ? "در حال تحلیل…" : "شروع تحلیل"}
      </Button>
    </div>
  );
}

/** One saved profile: its summary plus the run panel and the edit dialog. */
export function ProfileCard({
  botId,
  profile,
  uploads,
  onUploaded,
  onRun,
  onSaved,
}: {
  botId: string;
  profile: AnalysisProfileOut;
  uploads: UploadOut[];
  onUploaded: (upload: UploadOut) => void;
  onRun: (profile: AnalysisProfileOut, uploadId: string, narrative: boolean) => Promise<void>;
  onSaved: (profile: AnalysisProfileOut) => void;
}) {
  const [running, setRunning] = useState(false);
  const [editing, setEditing] = useState(false);
  const columns = profile.expected_columns ?? [];
  const metrics = profile.metrics ?? [];
  const checks = profile.checks ?? [];

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="text-sm">{profile.name}</CardTitle>
        {profile.daily_report && <Badge variant="accent">گزارش روزانه</Badge>}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1 text-sm text-muted-foreground">
          <span>
            برگه: <bdi>{profile.sheet || "-"}</bdi>
          </span>
          <span>
            {fa(metrics.length)} شاخص، {fa(checks.length)} بررسی · {fa(profile.runs_count)} اجرا
          </span>
          <span>ساخته‌شده در {formatDateTime(profile.created_at)}</span>
        </div>
        {columns.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="ستون‌های مورد انتظار">
            {columns.slice(0, CHIP_LIMIT).map((c) => (
              <li key={c}>
                <Badge variant="outline">
                  <bdi>{c}</bdi>
                </Badge>
              </li>
            ))}
            {columns.length > CHIP_LIMIT && (
              <li>
                <Badge variant="secondary">+{fa(columns.length - CHIP_LIMIT)}</Badge>
              </li>
            )}
          </ul>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={() => setRunning((v) => !v)} aria-expanded={running}>
            اجرای تحلیل
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setEditing(true)}>
            ویرایش
          </Button>
        </div>
        {running && <RunPanel botId={botId} profile={profile} uploads={uploads} onUploaded={onUploaded} onRun={onRun} />}
      </CardContent>
      {editing && (
        <ProfileEditDialog
          botId={botId}
          profile={profile}
          onClose={() => setEditing(false)}
          onSaved={(p) => {
            setEditing(false);
            onSaved(p);
          }}
        />
      )}
    </Card>
  );
}
