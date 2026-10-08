"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCheck, CircleX, Clock, Megaphone, Send, type LucideIcon } from "lucide-react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import type { AnnouncementIn, AnnouncementOut, Audience, GroupOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_TEXT = 3500;

const AUDIENCES: { id: Audience; label: string }[] = [
  { id: "everyone", label: "همه" },
  { id: "customers", label: "مشتریان" },
  { id: "staff", label: "همکاران" },
  { id: "managers", label: "مدیران" },
  { id: "subscribers", label: "مشترکان دسته" },
];

const STATUS: Record<string, { label: string; tone: "warning" | "info" | "success" | "danger"; icon: LucideIcon }> = {
  queued: { label: "در صف ارسال", tone: "warning", icon: Clock },
  sending: { label: "در حال ارسال", tone: "info", icon: Send },
  sent: { label: "ارسال شد", tone: "success", icon: CheckCheck },
  failed: { label: "ناموفق", tone: "danger", icon: CircleX },
};

const audienceLabel = (a: Audience) => AUDIENCES.find((x) => x.id === a)?.label ?? a;

/**
 * Composer for a one-off message to an audience (and optionally groups), plus the history of what was sent.
 * `?prefill=` fills the text and `?category=` aims it at the subscribers of that category (event drawers link here).
 */
export function AnnouncementsSection({ botId }: { botId: string }) {
  const params = useSearchParams();
  const prefill = params.get("prefill") ?? "";
  const prefillCategory = params.get("category") ?? "";

  const [history, setHistory] = useState<AnnouncementOut[] | null>(null);
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const [text, setText] = useState(prefill.slice(0, MAX_TEXT));
  const [audience, setAudience] = useState<Audience>(prefillCategory ? "subscribers" : "everyone");
  const [category, setCategory] = useState(prefillCategory);
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.listAnnouncements(botId).then(
      (h) => {
        if (cancelled) return;
        setHistory(h);
        setLoadError(null);
      },
      (err) => !cancelled && setLoadError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [botId, tick]);

  useEffect(() => {
    let cancelled = false;
    api.listGroups(botId).then(
      (g) => !cancelled && setGroups(g.filter((x) => x.active)),
      () => undefined, // groups are optional here
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);

  const trimmed = text.trim();
  const needsCategory = audience === "subscribers";
  const canSend = trimmed.length > 0 && text.length <= MAX_TEXT && (!needsCategory || category.trim().length > 0);

  function toggleGroup(chatId: number) {
    setGroupIds((ids) => (ids.includes(chatId) ? ids.filter((i) => i !== chatId) : [...ids, chatId]));
  }

  async function send() {
    const body: AnnouncementIn = {
      text: trimmed,
      audience,
      ...(needsCategory ? { category: category.trim() } : {}),
      ...(groupIds.length > 0 ? { group_chat_ids: groupIds } : {}),
    };
    const out = await api.createAnnouncement(botId, body);
    setHistory((h) => [out, ...(h ?? [])]);
    setText("");
    toast({ title: `اعلان برای ${fa(out.recipients)} نفر در صف ارسال قرار گرفت.`, tone: "success" });
  }

  const target = `${audienceLabel(audience)}${needsCategory && category.trim() ? ` «${category.trim()}»` : ""}${groupIds.length > 0 ? ` و ${fa(groupIds.length)} گروه` : ""}`;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <Card className="gap-5 p-5">
        <div className="flex flex-col gap-1">
          <h2 className="text-h3 text-fg">پیام تازه</h2>
          <p className="text-small text-fg-muted">یک پیام را برای مشتریان، همکاران یا مدیران (و گروه‌های انتخابی) در تلگرام بفرستید.</p>
        </div>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) setConfirming(true);
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="announcement-text">متن اعلان</Label>
            <Textarea
              id="announcement-text"
              rows={5}
              maxLength={MAX_TEXT}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="مثلاً: فردا ساعت ۱۰ فروشگاه دیرتر باز می‌شود."
            />
            <span className={cn("text-caption", text.length > MAX_TEXT * 0.9 ? "text-warning-text" : "text-fg-muted")}>
              {fa(text.length)} از {fa(MAX_TEXT)} نویسه
            </span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="announcement-audience">مخاطب</Label>
              <Select id="announcement-audience" value={audience} onChange={(e) => setAudience(e.target.value as Audience)}>
                {AUDIENCES.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label}
                  </option>
                ))}
              </Select>
            </div>
            {needsCategory && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="announcement-category">نام دسته</Label>
                <Input
                  id="announcement-category"
                  value={category}
                  maxLength={80}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="مثلاً: کارگاه‌ها"
                />
              </div>
            )}
          </div>

          {groups.length > 0 && (
            <fieldset className="flex flex-col gap-1">
              <legend className="mb-1 text-small font-medium text-fg">ارسال در گروه‌ها (اختیاری)</legend>
              {groups.map((g) => (
                <label key={g.chat_id} className="flex min-h-10 cursor-pointer items-center gap-2.5 text-small text-fg">
                  <input
                    type="checkbox"
                    className="size-4 accent-brand"
                    checked={groupIds.includes(g.chat_id)}
                    onChange={() => toggleGroup(g.chat_id)}
                  />
                  <span className="min-w-0 truncate">{g.title}</span>
                </label>
              ))}
            </fieldset>
          )}

          <div>
            <Button type="submit" disabled={!canSend}>
              <Send className="rtl:-scale-x-100" />
              ارسال اعلان
            </Button>
          </div>
        </form>
      </Card>

      <section aria-labelledby="announcement-history" className="flex flex-col gap-3">
        <h2 id="announcement-history" className="text-h3 text-fg">
          تاریخچه
        </h2>
        {loadError ? (
          <ErrorState message={loadError} onRetry={() => setTick((t) => t + 1)} />
        ) : !history ? (
          <div role="status" aria-label="در حال بارگذاری" className="flex flex-col gap-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : history.length === 0 ? (
          <div className="rounded-md border border-border bg-surface">
            <EmptyState icon={<Megaphone />} title="هنوز اعلانی نفرستاده‌اید" description="اولین پیام را از فرم کناری بفرستید؛ سابقهٔ ارسال‌ها اینجا می‌ماند." />
          </div>
        ) : (
          <ul className="rounded-md border border-border bg-surface">
            {history.map((a) => {
              const st = STATUS[a.status];
              const Icon = st?.icon;
              return (
                <li key={a.id} className="flex flex-col gap-1.5 border-b border-border px-4 py-3 last:border-b-0">
                  <p className="line-clamp-3 text-small break-words text-fg">{a.text}</p>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-fg-muted">
                    <StatusBadge tone={st?.tone ?? "neutral"} icon={Icon ? <Icon aria-hidden strokeWidth={1.75} /> : undefined} marker={!Icon}>
                      {st?.label ?? a.status}
                    </StatusBadge>
                    <span>{audienceLabel(a.audience)}</span>
                    <span>{fa(a.recipients)} گیرنده</span>
                    <time dateTime={a.created_at} className="ms-auto">
                      {formatDateTime(a.created_at)}
                    </time>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="ارسال اعلان؟"
        description={`این پیام برای «${target}» در تلگرام فرستاده می‌شود و پس از ارسال قابل بازگرداندن نیست.`}
        confirmLabel="ارسال اعلان"
        onConfirm={send}
      />
    </div>
  );
}
