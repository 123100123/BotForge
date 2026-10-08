"use client";

import { FileSpreadsheet, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { UploadOut } from "@/lib/types";
import { cn } from "@/lib/utils";
import { MAX_UPLOAD_BYTES } from "./labels";

const ACCEPTED = /\.(xlsx|csv)$/i;

/** Uploads one workbook (picker or drag and drop) and reports the stored upload with its inspection. */
export function UploadZone({
  botId,
  onUploaded,
  compact = false,
}: {
  botId: string;
  onUploaded: (upload: UploadOut) => void;
  compact?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(file: File | undefined) {
    if (!file || busy) return;
    setError(null);
    if (!ACCEPTED.test(file.name)) {
      setError("فقط فایل‌های اکسل (xlsx) و CSV پذیرفته می‌شوند.");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(`حجم فایل از حد مجاز (${fa(5)} مگابایت) بیشتر است.`);
      return;
    }
    setBusy(true);
    try {
      onUploaded(await api.uploadWorkbook(botId, file));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void send(e.dataTransfer.files[0]);
        }}
        aria-busy={busy}
        className={cn(
          "flex flex-col items-center gap-3 rounded-md border-2 border-dashed bg-card px-4 text-center transition-colors",
          compact ? "py-4" : "py-8",
          dragging ? "border-primary bg-accent/40" : "border-border",
          busy && "opacity-70",
        )}
      >
        {busy ? (
          <FileSpreadsheet className="size-7 animate-pulse text-brand-text" aria-hidden />
        ) : (
          <Upload className="size-7 text-muted-foreground" aria-hidden />
        )}
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium">
            {busy ? "در حال بارگذاری و بررسی فایل…" : "فایل را اینجا رها کنید یا از دکمهٔ زیر انتخاب کنید"}
          </p>
          <p className="text-caption text-muted-foreground">فایل xlsx یا CSV، حداکثر {fa(5)} مگابایت</p>
        </div>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.csv"
          className="sr-only"
          tabIndex={-1}
          aria-label="انتخاب فایل اکسل یا CSV"
          disabled={busy}
          onChange={(e) => void send(e.target.files?.[0])}
        />
        <Button type="button" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
          انتخاب فایل
        </Button>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
    </div>
  );
}
