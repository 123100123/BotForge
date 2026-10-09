"use client";

import { useState } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToggleField } from "@/components/data/controls";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { AnalysisProfileOut, UploadOut } from "@/lib/types";

/** Name and daily-report switch, then "create profile" from the inspected upload. */
export function ProfileCreateForm({
  botId,
  upload,
  onCreated,
}: {
  botId: string;
  upload: UploadOut;
  onCreated: (profile: AnalysisProfileOut) => void;
}) {
  const [name, setName] = useState("");
  const [daily, setDaily] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const trimmed = name.trim();
      const profile = await api.createAnalysisProfile(botId, {
        upload_id: upload.id,
        ...(trimmed ? { name: trimmed } : {}),
        daily_report: daily,
      });
      setName("");
      setDaily(false);
      onCreated(profile);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={create} className="flex flex-col gap-3 rounded-lg bg-surface-secondary/40 p-4">
      <p className="text-sm leading-7 text-muted-foreground">
        از ساختار این فایل یک پروفایل تحلیل قابل‌استفادهٔ مجدد بسازید؛ بعداً هر فایل هم‌ساختار را با یک کلیک تحلیل کنید.
      </p>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`profile-name-${upload.id}`}>نام پروفایل</Label>
        <Input
          id={`profile-name-${upload.id}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="مثلاً گزارش فروش روزانه"
          maxLength={80}
          disabled={busy}
        />
      </div>
      <div className="flex items-center gap-2">
        <ToggleField id={`profile-daily-${upload.id}`} label="گزارش روزانهٔ کارکنان" value={daily} onChange={setDaily} isDisabled={busy} />
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Button type="submit" isDisabled={busy} className="w-full sm:w-fit">
        {busy ? "در حال ساخت…" : "ساخت پروفایل تحلیل"}
      </Button>
    </form>
  );
}
