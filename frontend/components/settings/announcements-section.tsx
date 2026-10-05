"use client";

import { useEffect, useState } from "react";
import { Megaphone, Send } from "lucide-react";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime } from "@/lib/format";
import type { AnnouncementIn, AnnouncementOut, Audience, GroupOut } from "@/lib/types";

const MAX_TEXT = 3500;
const MAX_EXCERPT = 80;

const AUDIENCES: { id: Audience; label: string }[] = [
  { id: "everyone", label: "همه" },
  { id: "customers", label: "مشتریان" },
  { id: "staff", label: "همکاران" },
  { id: "managers", label: "مدیران" },
  { id: "subscribers", label: "مشترکان دسته" },
];

const STATUS: Record<string, { label: string; variant: "success" | "warning" | "destructive" | "secondary" }> = {
  queued: { label: "در صف ارسال", variant: "warning" },
  sending: { label: "در حال ارسال", variant: "warning" },
  sent: { label: "ارسال شد", variant: "success" },
  failed: { label: "ناموفق", variant: "destructive" },
};

const audienceLabel = (a: Audience) => AUDIENCES.find((x) => x.id === a)?.label ?? a;

function excerpt(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > MAX_EXCERPT ? `${flat.slice(0, MAX_EXCERPT)}…` : flat;
}

/** Composer for a one-off message to an audience (and optionally groups), plus the history of what was sent. */
export function AnnouncementsSection({ botId }: { botId: string }) {
  const [history, setHistory] = useState<AnnouncementOut[] | null>(null);
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [text, setText] = useState("");
  const [audience, setAudience] = useState<Audience>("everyone");
  const [category, setCategory] = useState("");
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.listAnnouncements(botId).then(
      (h) => !cancelled && setHistory(h),
      (err) => !cancelled && setLoadError(errorMessage(err)),
    );
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
  const canSend = trimmed.length > 0 && text.length <= MAX_TEXT && (!needsCategory || category.trim().length > 0) && !sending;

  function toggleGroup(chatId: number) {
    setGroupIds((ids) => (ids.includes(chatId) ? ids.filter((i) => i !== chatId) : [...ids, chatId]));
  }

  async function send() {
    if (!canSend) return;
    setSending(true);
    setError(null);
    setNotice(null);
    const body: AnnouncementIn = {
      text: trimmed,
      audience,
      ...(needsCategory ? { category: category.trim() } : {}),
      ...(groupIds.length > 0 ? { group_chat_ids: groupIds } : {}),
    };
    try {
      const out = await api.createAnnouncement(botId, body);
      setHistory((h) => [out, ...(h ?? [])]);
      setText("");
      setNotice(`اعلان برای ${fa(out.recipients)} نفر در صف ارسال قرار گرفت.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Megaphone className="size-5 text-muted-foreground" />
          اعلان‌ها
        </CardTitle>
        <CardDescription>یک پیام را برای مشتریان، همکاران یا مدیران (و گروه‌های انتخابی) در تلگرام بفرستید.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="announcement-text">متن اعلان</Label>
            <Textarea
              id="announcement-text"
              rows={4}
              maxLength={MAX_TEXT}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="مثلاً: فردا ساعت ۱۰ فروشگاه دیرتر باز می‌شود."
            />
            <span className="text-xs text-muted-foreground">
              {fa(text.length)} از {fa(MAX_TEXT)} نویسه
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
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
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-medium">ارسال در گروه‌ها (اختیاری)</legend>
              {groups.map((g) => (
                <label key={g.chat_id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={groupIds.includes(g.chat_id)}
                    onChange={() => toggleGroup(g.chat_id)}
                  />
                  <span className="min-w-0 truncate">{g.title}</span>
                </label>
              ))}
            </fieldset>
          )}

          {error && <ErrorNote>{error}</ErrorNote>}
          {notice && <InfoNote>{notice}</InfoNote>}
          <div>
            <Button type="submit" disabled={!canSend}>
              <Send className="rtl:-scale-x-100" />
              {sending ? "در حال ارسال…" : "ارسال اعلان"}
            </Button>
          </div>
        </form>

        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">تاریخچه</h3>
          {loadError && <ErrorNote>{loadError}</ErrorNote>}
          {!history ? (
            !loadError && <div role="status" aria-label="در حال بارگذاری" className="h-16 animate-pulse rounded-xl bg-muted" />
          ) : history.length === 0 ? (
            <p className="text-sm leading-7 text-muted-foreground">هنوز اعلانی نفرستاده‌اید.</p>
          ) : (
            <ul className="flex flex-col divide-y rounded-md border">
              {history.map((a) => {
                const st = STATUS[a.status] ?? { label: a.status, variant: "secondary" as const };
                return (
                  <li key={a.id} className="flex flex-col gap-1.5 px-3 py-3">
                    <p className="text-sm leading-7 break-words">{excerpt(a.text)}</p>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant="outline">{audienceLabel(a.audience)}</Badge>
                      <span>{fa(a.recipients)} گیرنده</span>
                      <Badge variant={st.variant}>{st.label}</Badge>
                      <span className="ms-auto">{formatDateTime(a.created_at)}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
