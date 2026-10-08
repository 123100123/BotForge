"use client";

import { useOpenSection } from "@/components/app/shell/use-open-section";
import { useEffect, useState } from "react";
import { CalendarClock } from "lucide-react";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
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

/** Daily and weekly summaries sent to the owner in Telegram. Delivery needs the scheduled_reports capability. */
export function SchedulesSection({ botId }: { botId: string }) {
  const openSection = useOpenSection();
  const [saved, setSaved] = useState<ScheduleOut[] | null>(null);
  const [draft, setDraft] = useState<ScheduleOut[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getSchedules(botId).then(
      (s) => {
        if (cancelled) return;
        setSaved(s);
        setDraft(s);
      },
      (err) => !cancelled && setLoadError(errorMessage(err)),
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarClock className="size-5 text-muted-foreground" />
          گزارش‌های زمان‌بندی‌شده
        </CardTitle>
        <CardDescription>خلاصهٔ کسب‌وکار را در ساعت دلخواه به‌صورت خودکار در تلگرام دریافت کنید.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="rounded-sm bg-muted/50 p-3 text-sm leading-7 text-muted-foreground">
          ارسال گزارش‌ها فقط وقتی انجام می‌شود که قابلیت «گزارش زمان‌بندی‌شده» فعال باشد.{" "}
          <button type="button" className="text-brand-text underline-offset-4 hover:underline" onClick={() => openSection("capabilities")}>
            رفتن به قابلیت‌ها
          </button>
        </p>

        {loadError && <ErrorNote>{loadError}</ErrorNote>}
        {!saved ? (
          !loadError && <div role="status" aria-label="در حال بارگذاری" className="h-24 animate-pulse rounded-md bg-border" />
        ) : draft.length === 0 ? (
          <p className="text-sm leading-7 text-muted-foreground">زمان‌بندی‌ای تعریف نشده است.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {draft.map((s) => {
              const timeBad = !TIME_RE.test(s.time);
              return (
                <li key={s.id} className="flex flex-col gap-3 rounded-sm border p-3">
                  <div className="flex items-center gap-3">
                    <Switch
                      id={`schedule-${s.id}`}
                      checked={s.enabled}
                      onCheckedChange={(on) => patch(s.id, { enabled: on })}
                      aria-label={`فعال بودن ${KIND_LABELS[s.kind]}`}
                    />
                    <Label htmlFor={`schedule-${s.id}`} className="text-sm font-medium">
                      {KIND_LABELS[s.kind]}
                    </Label>
                    <Badge variant={s.enabled ? "success" : "secondary"} className="ms-auto">
                      {s.enabled ? "فعال" : "غیرفعال"}
                    </Badge>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`schedule-time-${s.id}`}>ساعت ارسال</Label>
                      <Input
                        id={`schedule-time-${s.id}`}
                        type="time"
                        dir="ltr"
                        className="text-start"
                        value={s.time}
                        aria-invalid={timeBad}
                        onChange={(e) => patch(s.id, { time: e.target.value })}
                      />
                    </div>
                    {s.kind === "weekly_summary" && (
                      <div className="flex flex-col gap-1.5">
                        <Label htmlFor={`schedule-day-${s.id}`}>روز هفته</Label>
                        <Select
                          id={`schedule-day-${s.id}`}
                          value={s.weekday ?? ""}
                          onChange={(e) => patch(s.id, { weekday: e.target.value === "" ? null : Number(e.target.value) })}
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
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-caption text-muted-foreground">شامل:</span>
                      {s.metrics.map((m) => (
                        <Badge key={m} variant="outline">
                          {METRIC_LABELS[m] ?? m}
                        </Badge>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {error && <ErrorNote>{error}</ErrorNote>}
        {notice && <InfoNote>{notice}</InfoNote>}
        {saved && draft.length > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={save} disabled={!dirty || invalid || saving}>
              {saving ? "در حال ذخیره…" : "ذخیرهٔ زمان‌بندی"}
            </Button>
            {invalid && <span className="text-sm text-danger-text">ساعت و روز هفته را کامل وارد کنید.</span>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
