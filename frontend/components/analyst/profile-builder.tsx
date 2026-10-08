"use client";

import { Loader2Icon, MessageCircleQuestionIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { AnalysisProfileOut } from "@/lib/types";
import { AssistantLimit, isDailyCap } from "./assistant-limit";

type Phase = "idle" | "drafting" | "cancelled" | "limit" | "error";

/**
 * «ساخت پروفایل با دستیار»: one assistant call that proposes what to measure and check for an upload. The wait
 * is cancellable. The request itself cannot be recalled, so if the answer arrives after a cancel it is not
 * thrown away silently: `onLate` receives it (the profile exists on the server and shows in the list).
 */
export function ProfileBuilder({
  botId,
  uploadId,
  initialName = "",
  daily = false,
  onCreated,
  onLate,
  submitLabel = "ساخت پروفایل با دستیار",
}: {
  botId: string;
  uploadId: string;
  initialName?: string;
  daily?: boolean;
  onCreated: (profile: AnalysisProfileOut) => void;
  onLate?: (profile: AnalysisProfileOut) => void;
  submitLabel?: string;
}) {
  const [name, setName] = useState(initialName);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const attempt = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function start() {
    const mine = ++attempt.current;
    setPhase("drafting");
    setError(null);
    try {
      const trimmed = name.trim();
      const profile = await api.createAnalysisProfile(botId, { upload_id: uploadId, ...(trimmed ? { name: trimmed } : {}), daily_report: daily });
      if (attempt.current !== mine) {
        onLate?.(profile);
        return;
      }
      if (mounted.current) onCreated(profile);
    } catch (err) {
      if (attempt.current !== mine || !mounted.current) return;
      if (isDailyCap(err)) setPhase("limit");
      else {
        setError(errorMessage(err));
        setPhase("error");
      }
    }
  }

  function cancel() {
    attempt.current += 1;
    setPhase("cancelled");
  }

  if (phase === "drafting") {
    return (
      <div role="status" className="flex flex-col items-start gap-3 rounded-sm bg-surface-sunken p-4">
        <p className="flex items-center gap-2 text-body font-medium text-fg">
          <Loader2Icon aria-hidden className="size-5 animate-spin text-brand-text" strokeWidth={1.75} />
          دستیار در حال پیشنهاد شاخص‌هاست…
        </p>
        <p className="text-small text-fg-muted">معمولاً چند ثانیه طول می‌کشد. می‌توانید صبر کنید یا انصراف دهید.</p>
        <Button type="button" variant="secondary" size="sm" onClick={cancel}>
          انصراف
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {phase === "limit" ? (
        <AssistantLimit />
      ) : (
        <>
          <div className="flex max-w-md flex-col gap-1.5">
            <Label htmlFor={`profile-name-${uploadId}`}>نام پروفایل (اختیاری)</Label>
            <Input
              id={`profile-name-${uploadId}`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="مثلاً گزارش فروش روزانه"
              maxLength={80}
            />
            <p className="text-caption text-fg-muted">اگر نام نگذارید، دستیار یک نام پیشنهاد می‌دهد.</p>
          </div>
          {phase === "cancelled" && (
            <p role="status" className="text-small text-fg-secondary">
              انتظار لغو شد. اگر دستیار جواب را رسانده باشد، پروفایل در فهرست پروفایل‌ها دیده می‌شود.
            </p>
          )}
          {phase === "error" && error && <ErrorNote>{error}</ErrorNote>}
          <div className="flex flex-col items-start gap-1.5">
            <Button type="button" onClick={() => void start()}>
              <MessageCircleQuestionIcon aria-hidden />
              {phase === "error" ? "تلاش دوباره" : submitLabel}
            </Button>
            <p className="text-caption text-fg-muted">این کار یک بار از سهمیهٔ روزانهٔ دستیار ({fa(30)} بار در هر ۲۴ ساعت برای هر حساب) مصرف می‌کند.</p>
          </div>
        </>
      )}
    </div>
  );
}
