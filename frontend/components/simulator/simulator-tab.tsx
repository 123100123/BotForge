"use client";

import { useRef, useState, type FormEvent } from "react";
import { FlaskConical, Play, RotateCcw, SendHorizontal } from "lucide-react";
import { defaultRevision, isTestable, REVISION_STATUS_LABELS, revisionOptionLabel } from "@/components/app/revision-labels";
import { useOpenSection } from "@/components/app/shell/use-open-section";
import { ErrorNote, InfoNote, LoadingBlock } from "@/components/app/state-blocks";
import { useRevisions } from "@/components/app/use-revisions";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { Bot, Persona } from "@/lib/types";
import { applyResponse, emptyChats, emptyUnread, PERSONAS, type ChatItem, type Chats, type Unread } from "./chat";
import { ChatMessageList, type ChatMessage } from "./chat-message-list";
import { PersonaSwitcher } from "./persona-switcher";
import { PhoneFrame } from "./phone-frame";

/**
 * Bot test page body: a controls panel (persona, version, start/reset) and the phone.
 * `initialRevisionId` preselects a version (from `?revision=` when linked from a change proposal).
 */
export function SimulatorTab({ bot, initialRevisionId = null }: { bot: Bot; initialRevisionId?: string | null }) {
  const openSection = useOpenSection();
  const { revisions, error: loadError } = useRevisions(bot.id, bot.active_revision_id);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [persona, setPersona] = useState<Persona>("ali");
  // Transcripts live in component state only; the endpoint does not keep them.
  const [conv, setConv] = useState<{ chats: Chats; unread: Unread }>(() => ({ chats: emptyChats(), unread: emptyUnread() }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const counter = useRef(0);
  const nextId = () => (counter.current += 1);

  // Only a draft or the active revision can be tried. Default: the linked one, else the draft under review, else the active one.
  const selectable = (revisions ?? []).filter(isTestable);
  const linked = initialRevisionId ? selectable.find((r) => r.id === initialRevisionId) : undefined;
  const revisionId = pickedId ?? linked?.id ?? defaultRevision(selectable)?.id ?? null;
  const revision = selectable.find((r) => r.id === revisionId) ?? null;
  // A linked version that cannot be tried: say so instead of silently testing another one.
  const unlinked = !!initialRevisionId && !!revisions && !linked && pickedId === null ? (revisions.find((r) => r.id === initialRevisionId) ?? null) : undefined;
  const skippedNotice =
    unlinked === undefined
      ? null
      : `${unlinked ? `نسخهٔ ${fa(unlinked.number)}` : "نسخهٔ درخواستی"} را نمی‌توان آزمایش کرد؛ ${revision?.status === "draft" ? "پیش‌نویس" : "نسخهٔ فعال"} انتخاب شد.`;

  if (loadError) return <ErrorNote>{loadError}</ErrorNote>;
  if (!revisions) return <LoadingBlock />;
  if (selectable.length === 0) {
    return (
      <div className="rounded-md border border-border bg-surface">
        <EmptyState
          icon={<FlaskConical strokeWidth={1.75} />}
          as="h2"
          title="هنوز چیزی برای امتحان کردن نیست"
          description="ابتدا در «تغییرات» ربات را بسازید؛ بعد می‌توانید پیش‌نویس را اینجا با چند کاربر آزمایشی امتحان کنید."
          action={
            <Button variant="secondary" onClick={() => openSection("changes")}>
              رفتن به تغییرات
            </Button>
          }
        />
      </div>
    );
  }

  const personaLabel = PERSONAS.find((p) => p.id === persona)?.label ?? "";
  const items = conv.chats[persona];
  const messages: ChatMessage[] = items.map((i) => ({
    id: i.id,
    from: i.from === "me" ? "user" : "bot",
    text: i.text,
    buttons: i.buttons.map((row) => row.map((b) => b.label)),
  }));

  async function send(kind: "start" | "text" | "callback", opts: { text?: string; data?: string; label?: string; sourceId?: number } = {}) {
    if (busy) return;
    setBusy(true);
    setError(null);
    const acting = persona;
    const shown = opts.label ?? opts.text;
    const mine: ChatItem = { id: nextId(), from: "me", text: shown ?? "/start", buttons: [] };
    setConv((c) => ({ ...c, chats: { ...c.chats, [acting]: [...c.chats[acting], mine] } }));
    try {
      const response = await api.simulatorEvent(bot.id, {
        revision_id: revisionId,
        persona: acting,
        kind,
        ...(opts.text !== undefined ? { text: opts.text } : {}),
        ...(opts.data !== undefined ? { data: opts.data } : {}),
      });
      setConv((c) => applyResponse(c.chats, c.unread, acting, response, opts.sourceId ?? null, nextId));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function reset(nextRevisionId: string | null) {
    setBusy(true);
    setError(null);
    try {
      await api.simulatorReset(bot.id, nextRevisionId);
      setConv({ chats: emptyChats(), unread: emptyUnread() });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    setText("");
    void send("text", { text: value });
  }

  const badge = revision && (
    <StatusBadge tone={revision.status === "active" ? "success" : "neutral"} marker>
      {REVISION_STATUS_LABELS[revision.status]}
    </StatusBadge>
  );

  return (
    <div className="grid gap-6 md:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] md:items-start">
      <section aria-labelledby="sim-controls-title" className="rounded-md border border-border bg-surface">
        <h2 id="sim-controls-title" className="p-5 text-h3 text-fg">
          تنظیم آزمایش
        </h2>
        <div className="flex flex-col gap-2 border-t border-border p-5">
          <Label>کاربر آزمایشی</Label>
          <PersonaSwitcher
            value={persona}
            unread={conv.unread}
            onChange={(p) => {
              setPersona(p);
              setConv((c) => ({ ...c, unread: { ...c.unread, [p]: 0 } }));
            }}
          />
        </div>
        <div className="flex flex-col gap-2 border-t border-border p-5">
          <Label htmlFor="sim-revision">نسخهٔ مورد آزمایش</Label>
          <Select
            id="sim-revision"
            value={revisionId ?? ""}
            onChange={(e) => {
              setPickedId(e.target.value);
              void reset(e.target.value);
            }}
            disabled={busy}
          >
            {selectable.map((r) => (
              <option key={r.id} value={r.id}>
                {revisionOptionLabel(r)}
              </option>
            ))}
          </Select>
          {skippedNotice && <InfoNote tone="warning">{skippedNotice}</InfoNote>}
        </div>
        <div className="flex flex-col gap-3 border-t border-border p-5">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void send("start")} disabled={busy}>
              <Play strokeWidth={1.75} />
              شروع
            </Button>
            <Button variant="secondary" onClick={() => void reset(revisionId)} disabled={busy}>
              <RotateCcw strokeWidth={1.75} />
              بازنشانی
            </Button>
          </div>
          {error && <ErrorNote>{error}</ErrorNote>}
        </div>
        <p className="border-t border-border p-5 text-small text-fg-muted">
          این گفتگو فقط آزمایشی است و به تلگرام نمی‌رود. وقتی پیامی برای کاربر دیگری برسد (مثلاً اعلان ثبت‌نام برای مدیر)، روی نام او نشانگر می‌بینید.
        </p>
      </section>

      <PhoneFrame
        title={bot.name}
        subtitle={`در نقش ${personaLabel}${revision ? ` · نسخهٔ ${fa(revision.number)}` : ""}`}
        badge={badge}
        footer={
          <form onSubmit={submit} className="flex items-center gap-2">
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="پیام…" aria-label="پیام" disabled={busy} />
            <Button type="submit" size="icon" aria-label="ارسال" disabled={busy || text.trim() === ""}>
              <SendHorizontal strokeWidth={1.75} className="rtl:-scale-x-100" />
            </Button>
          </form>
        }
      >
        <ChatMessageList
          autoScroll
          messages={messages}
          disabled={busy}
          emptyText="گفتگو خالی است. برای شروع، دکمهٔ «شروع» را بزنید."
          onButtonPress={(mi, r, c) => {
            const item = items[mi];
            const b = item?.buttons[r]?.[c];
            if (item && b) void send("callback", { data: b.data, label: b.label, sourceId: item.id });
          }}
        />
      </PhoneFrame>
    </div>
  );
}
