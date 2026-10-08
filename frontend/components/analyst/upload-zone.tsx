"use client";

import { CircleAlertIcon, FileSpreadsheetIcon, Loader2Icon, UploadIcon } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { UploadOut } from "@/lib/types";
import { cn } from "@/lib/utils";
import { fileSizeText, MAX_UPLOAD_BYTES } from "./labels";

const ACCEPTED = /\.(xlsx|csv)$/i;

/**
 * Uploads one workbook (a keyboard-reachable button, or drag and drop) and reports the stored upload with its
 * inspection. While it works it shows the file's name and size; the request has no byte progress, so the
 * state is "uploading and reading the structure" rather than a percentage.
 */
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
  const [busy, setBusy] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(file: File | undefined) {
    if (!file || busy) return;
    setError(null);
    if (!ACCEPTED.test(file.name)) {
      setError("فقط فایل اکسل (xlsx) و CSV پذیرفته می‌شود. فایل دیگری انتخاب کنید.");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(`حجم این فایل ${fileSizeText(file.size)} است و از حد مجاز (${fa(5)} مگابایت) بیشتر است.`);
      return;
    }
    setBusy(file);
    try {
      onUploaded(await api.uploadWorkbook(botId, file));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
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
        aria-busy={!!busy}
        className={cn(
          "flex flex-col items-center gap-3 rounded-md border border-dashed px-4 text-center transition-colors duration-fast",
          compact ? "py-5" : "py-10",
          dragging ? "border-brand bg-brand-soft" : "border-border-strong bg-surface-sunken",
        )}
      >
        <span aria-hidden className="flex size-11 items-center justify-center rounded-md bg-surface text-fg-muted">
          {busy ? <Loader2Icon className="size-5 animate-spin text-brand-text" strokeWidth={1.75} /> : <FileSpreadsheetIcon className="size-5" strokeWidth={1.75} />}
        </span>
        <div className="flex flex-col gap-1" role="status">
          {busy ? (
            <>
              <p className="text-body font-medium text-fg">در حال بارگذاری و خواندن ساختار فایل…</p>
              <p className="text-small text-fg-muted">
                <bdi>{busy.name}</bdi> · {fileSizeText(busy.size)}
              </p>
            </>
          ) : (
            <>
              <p className="text-body font-medium text-fg">فایل را اینجا رها کنید یا آن را انتخاب کنید</p>
              <p className="text-small text-fg-muted">فایل xlsx یا CSV، حداکثر {fa(5)} مگابایت</p>
            </>
          )}
        </div>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.csv"
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          disabled={!!busy}
          onChange={(e) => void send(e.target.files?.[0])}
        />
        <Button type="button" variant="secondary" disabled={!!busy} onClick={() => input.current?.click()}>
          <UploadIcon aria-hidden />
          انتخاب فایل
        </Button>
      </div>
      {error && (
        <p role="alert" className="flex items-start gap-2 rounded-sm bg-danger-soft p-3 text-small text-danger-text">
          <CircleAlertIcon aria-hidden className="mt-1 size-4 shrink-0" strokeWidth={1.75} />
          {error}
        </p>
      )}
    </div>
  );
}
