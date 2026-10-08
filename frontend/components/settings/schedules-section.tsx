"use client";

import Link from "next/link";
import { CalendarClockIcon, TriangleAlertIcon } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { botHref } from "@/lib/routes";
import type { ScheduleOut } from "@/lib/types";

/** Backend weekday numbers (0 = Monday ... 6 = Sunday), listed Saturday first as in the Iranian week. */
const WEEKDAYS: { value: number; label: string }[] = [
  { value: 5, label: "شنبه" },
  { value: 6, label: "یکشنبه" },
  { value: 0, label: "دوشنبه" },
  { value: 1, label: "سه‌شنبه" },
  { value: 2, label: "چهارشنبه" },
  { value: 3, label: "پنجشنبه" },
  { value: 4, label: "جمعه" },
];

const KIND_LABELS: Record<ScheduleOut["kind"], string> = { daily_summary: "خلاصهٔ روزانه", weekly_summary: "خلاصهٔ هفتگی" };

const METRIC_LABELS: Record<string, string> = {
  bookings: "ثبت‌نام‌ها",
  orders: "سفارش‌ها",
  revenue: "درآمد",
  requests: "درخواست‌ها",
  customers: "مشتریان",
};

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const CAPABILITY_ID = "scheduled_reports";

function SchedulePanel({ schedule: s, onChange }: { schedule: ScheduleOut; onChange: (change: Partial<ScheduleOut>) => void }) {
  const uid = useId();
  const titleId = `${uid}-title`;
  const timeBad = !TIME_RE.test(s.time);
  return (
    <section aria-labelledby={titleId} className="flex flex-col gap-4 rounded-md border border-border bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 id={titleId} className="text-h3 text-fg">
          {KIND_LABELS[s.kind]}
        </h3>
        <div className="flex items-center gap-2">
          <Label htmlFor={`${uid}-on`} className="text-small text-fg-secondary">
            {s.enabled ? "فعال" : "غیرفعال"}
          </Label>
          <Switch id={`${uid}-on`} checked={s.enabled} onCheckedChange={(on) => onChange({ enabled: on })} />
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${uid}-time`}>ساعت ارسال</Label>
          <Input
            id={`${uid}-time`}
            type="time"
            dir="ltr"
            className="text-start"
            value={s.time}
            aria-invalid={timeBad}
            onChange={(e) => onChange({ time: e.target.value })}
          />
        </div>
        {s.kind === "weekly_summary" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${uid}-day`}>روز هفته</Label>
            <Select
              id={`${uid}-day`}
              value={s.weekday ?? ""}
              aria-invalid={s.weekday === null}
              onChange={(e) => onChange({ weekday: e.target.value === "" ? null : Number(e.target.value) })}
            >
              {s.weekday === null && <option value="">انتخاب کنید</option>}
              {WEEKDAYS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </Select>
          </div>
        )}
      </div>
      {s.metrics.length > 0 && (
        <div className="flex flex-col gap-2">
          <h4 className="text-small text-fg-secondary">شاخص‌های همراه خلاصه</h4>
          <ul className="flex flex-wrap gap-1.5">
            {s.metrics.map((m) => (
              <li key={m}>
                <Badge variant="outline">{METRIC_LABELS[m] ?? m}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/**
 * Daily and weekly summaries sent to the owner in Telegram, as a panel per schedule. Delivery needs the
 * scheduled_reports capability; when it is off, a note links to it.
 */
export function SchedulesSection({ botId }: { botId: string }) {
  const [saved, setSaved] = useState<ScheduleOut[] | null>(null);
  const [draft, setDraft] = useState<ScheduleOut[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [capEnabled, setCapEnabled] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getSchedules(botId).then(
      (s) => {
        if (cancelled) return;
        setLoadError(null);
        setSaved(s);
        setDraft(s);
      },
      (err) => !cancelled && setLoadError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [botId, attempt]);

  // Only to know whether delivery is on; if the lookup fails the note is simply not shown.
  useEffect(() => {
    let cancelled = false;
    api.listCapabilities(botId).then(
      (list) => {
        if (cancelled) return;
        const cap = list.categories.flatMap((c) => c.capabilities).find((c) => c.id === CAPABILITY_ID);
        setCapEnabled(cap ? cap.enabled : null);
      },
      () => {},
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);

  function patch(id: string, change: Partial<ScheduleOut>) {
    setNotice(null);
    setDraft((list) => list.map((s) => (s.id === id ? { ...s, ...change } : s)));
  }

  const dirty = saved !== null && JSON.stringify(saved) !== JSON.stringify(draft);
  const invalid = draft.some((s) => !TIME_RE.test(s.time) || (s.kind === "weekly_summary" && s.weekday === null));

  async function save() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = await api.putSchedules(botId, { schedules: draft });
      setSaved(next);
      setDraft(next);
      setNotice("زمان‌بندی ذخیره شد.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="schedules-title" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="schedules-title" className="flex items-center gap-2 text-h2 text-fg">
          <CalendarClockIcon aria-hidden className="size-5 text-fg-muted" strokeWidth={1.75} />
          ارسال زمان‌بندی‌شده
        </h2>
        <p className="text-small text-fg-secondary">خلاصهٔ کسب‌وکار را در ساعت دلخواه به‌صورت خودکار در تلگرام دریافت کنید.</p>
      </div>

      {capEnabled === false && (
        <p role="status" className="flex items-start gap-3 rounded-sm bg-warning-soft p-3 text-small text-warning-text">
          <TriangleAlertIcon aria-hidden className="mt-1 size-4 shrink-0" strokeWidth={1.75} />
          <span>
            تا قابلیت «گزارش زمان‌بندی‌شده» روشن نباشد، چیزی ارسال نمی‌شود.{" "}
            <Link href={`${botHref(botId)}/capabilities/${CAPABILITY_ID}`} className="font-medium underline underline-offset-4">
              روشن‌کردن در قابلیت‌ها
            </Link>
          </span>
        </p>
      )}

      {loadError ? (
        <ErrorState message={loadError} onRetry={() => setAttempt((a) => a + 1)} />
      ) : !saved ? (
        <div role="status" aria-label="در حال بارگذاری" className="flex flex-col gap-4">
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      ) : draft.length === 0 ? (
        <div className="rounded-md border border-border bg-surface">
          <EmptyState icon={<CalendarClockIcon />} title="زمان‌بندی‌ای تعریف نشده است" description="بعد از روشن‌کردن قابلیت گزارش زمان‌بندی‌شده، خلاصهٔ روزانه و هفتگی اینجا ظاهر می‌شود." />
        </div>
      ) : (
        <>
          {draft.map((s) => (
            <SchedulePanel key={s.id} schedule={s} onChange={(change) => patch(s.id, change)} />
          ))}
          {error && <ErrorNote>{error}</ErrorNote>}
          {notice && <InfoNote>{notice}</InfoNote>}
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void save()} loading={saving} disabled={!dirty || invalid}>
              ذخیرهٔ زمان‌بندی
            </Button>
            {invalid && <span className="text-small text-danger-text">ساعت و روز هفته را کامل وارد کنید.</span>}
          </div>
        </>
      )}
    </section>
  );
}
