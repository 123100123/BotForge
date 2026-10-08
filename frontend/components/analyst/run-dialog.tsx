"use client";

import { useState } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import type { AnalysisProfileOut, UploadOut } from "@/lib/types";
import { UploadZone } from "./upload-zone";

/**
 * «اجرای تحلیل»: pick the profile and the file (an earlier upload or a new one) and run it. The result opens as
 * a report page, so the dialog only closes once the run exists.
 */
export function RunDialog({
  botId,
  profiles,
  uploads,
  initialProfileId,
  onUploaded,
  onRun,
  onClose,
}: {
  botId: string;
  profiles: AnalysisProfileOut[];
  uploads: UploadOut[];
  initialProfileId?: string;
  onUploaded: (upload: UploadOut) => void;
  onRun: (profile: AnalysisProfileOut, uploadId: string, narrative: boolean) => Promise<void>;
  onClose: () => void;
}) {
  const [profileId, setProfileId] = useState(initialProfileId ?? profiles[0]?.id ?? "");
  const [chosen, setChosen] = useState<string | null>(null);
  const [narrative, setNarrative] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const profile = profiles.find((p) => p.id === profileId) ?? profiles[0];
  const uploadId = uploads.find((u) => u.id === chosen)?.id ?? uploads[0]?.id ?? "";

  async function run() {
    if (!profile || !uploadId) return;
    setBusy(true);
    setError(null);
    try {
      await onRun(profile, uploadId, narrative);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>اجرای تحلیل</DialogTitle>
          <DialogDescription>یک فایل را با یکی از پروفایل‌ها تحلیل کنید. فایل باید همان ساختار فایلی را داشته باشد که پروفایل از آن ساخته شده.</DialogDescription>
        </DialogHeader>

        {profiles.length > 1 && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="run-profile">پروفایل تحلیل</Label>
            <Select id="run-profile" value={profile?.id ?? ""} onChange={(e) => setProfileId(e.target.value)} disabled={busy}>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
        )}

        {uploads.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="run-upload">فایل برای تحلیل</Label>
            <Select id="run-upload" value={uploadId} onChange={(e) => setChosen(e.target.value)} disabled={busy}>
              {uploads.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.filename} · {formatDateTime(u.created_at)}
                </option>
              ))}
            </Select>
          </div>
        )}

        <div className="flex flex-col gap-2">
          <span className="text-small text-fg-secondary">{uploads.length > 0 ? "یا فایل تازه‌ای بارگذاری کنید" : "برای شروع، یک فایل بارگذاری کنید"}</span>
          <UploadZone
            botId={botId}
            compact
            onUploaded={(u) => {
              setChosen(u.id);
              onUploaded(u);
            }}
          />
        </div>

        <div className="flex items-start gap-3">
          <Switch id="run-narrative" checked={narrative} onCheckedChange={setNarrative} disabled={busy} className="mt-1" />
          <div className="flex flex-col gap-0.5">
            <Label htmlFor="run-narrative">نوشتن خلاصهٔ دستیار از نتیجه</Label>
            <p className="text-caption text-fg-muted">یک بار از سهمیهٔ روزانهٔ دستیار ({fa(30)} بار در هر ۲۴ ساعت) مصرف می‌کند. اگر تمام شده باشد، گزارش بدون خلاصه ساخته می‌شود.</p>
          </div>
        </div>

        {error && <ErrorNote>{error}</ErrorNote>}
        <DialogFooter>
          <Button type="button" loading={busy} disabled={!uploadId || !profile} onClick={() => void run()}>
            شروع تحلیل
          </Button>
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            انصراف
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
