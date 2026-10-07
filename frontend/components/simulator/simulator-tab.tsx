"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, RotateCcw } from "lucide-react";
import type { WorkspaceTab } from "@/components/app/workspace";
import { defaultRevision, revisionOptionLabel } from "@/components/app/revision-labels";
import { EmptyState, ErrorNote, InfoNote, LoadingBlock } from "@/components/app/state-blocks";
import { useRevisions } from "@/components/app/use-revisions";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { ApiError, ERROR_CODES, errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { Bot, Persona, RuntimeButton } from "@/lib/types";
import { applyResponse, emptyChats, emptyUnread, PERSONAS, type ChatItem, type Chats, type Unread } from "./chat";
import { PersonaSwitcher } from "./persona-switcher";
import { PhoneFrame } from "./phone-frame";

/** The revision sent is no longer a draft or the active one (approved over, rolled back, rejected). */
function isStaleRevision(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 409 &&
    (err.code === ERROR_CODES.revisionNotSimulatable || err.code === ERROR_CODES.noActiveRevision)
  );
}

interface SimulatorTabProps {
  bot: Bot;
  /** Refetches the bot (its active revision may have changed elsewhere). */
  onBotChanged: () => void;
  onOpenTab: (tab: WorkspaceTab) => void;
}

export function SimulatorTab({ bot, onBotChanged, onOpenTab }: SimulatorTabProps) {
  // Refetched whenever the bot's active revision changes (approval in the Agent tab, rollback in Versions).
  const { revisions, error: loadError, reload } = useRevisions(bot.id, bot.active_revision_id);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [persona, setPersona] = useState<Persona>("ali");
  // Transcripts live in component state only; the endpoint does not keep them.
  const [conv, setConv] = useState<{ chats: Chats; unread: Unread }>(() => ({ chats: emptyChats(), unread: emptyUnread() }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const counter = useRef(0);
  const nextId = () => (counter.current += 1);
  /** Revision the current conversation and sandbox belong to. */
  const sessionRevision = useRef<string | null>(null);

  // Default: the draft under review if there is one, otherwise the active revision. A picked revision
  // that is no longer a draft or the active one falls back to the default.
  const selectable = (revisions ?? []).filter((r) => r.status === "draft" || r.status === "active");
  const revisionId =
    selectable.find((r) => r.id === pickedId)?.id ?? defaultRevision(selectable)?.id ?? null;
  const revisionNumber = selectable.find((r) => r.id === revisionId)?.number ?? null;

  /** On a stale revision, rereads the bot and its revisions; the change of `revisionId` then resets the session. */
  const fail = useCallback(
    (err: unknown) => {
      setError(errorMessage(err));
      if (isStaleRevision(err)) {
        onBotChanged();
        reload();
      }
    },
    [onBotChanged, reload],
  );

  const reset = useCallback(
    async (nextRevisionId: string | null, nextNotice: string | null = null) => {
      sessionRevision.current = nextRevisionId;
      setBusy(true);
      setError(null);
      setNotice(nextNotice);
      try {
        await api.simulatorReset(bot.id, nextRevisionId);
        setConv({ chats: emptyChats(), unread: emptyUnread() });
      } catch (err) {
        fail(err);
      } finally {
        setBusy(false);
      }
    },
    [bot.id, fail],
  );

  // The revision under test changed without the owner picking it (a new active revision or a new
  // draft): start a fresh session on it, as picking it in the selector would.
  useEffect(() => {
    if (revisionId === null || revisionId === sessionRevision.current) return;
    const first = sessionRevision.current === null;
    sessionRevision.current = revisionId;
    if (first) return;
    const label = revisionNumber !== null ? `نسخهٔ ${fa(revisionNumber)}` : "نسخهٔ تازه";
    void reset(revisionId, `نسخه‌های ربات تغییر کرد؛ شبیه‌ساز حالا ${label} را آزمایش می‌کند و گفتگو از نو شروع شد.`);
  }, [revisionId, revisionNumber, reset]);

  if (loadError) return <ErrorNote>{loadError}</ErrorNote>;
  if (!revisions) return <LoadingBlock />;
  if (selectable.length === 0) {
    return (
      <EmptyState
        title="هنوز چیزی برای امتحان کردن نیست"
        action={
          <Button variant="outline" onClick={() => onOpenTab("agent")}>
            رفتن به تب ایجنت
          </Button>
        }
      >
        ابتدا در تب ایجنت ربات را بسازید؛ بعد می‌توانید پیش‌نویس را اینجا با چند کاربر آزمایشی امتحان کنید.
      </EmptyState>
    );
  }

  const personaLabel = PERSONAS.find((p) => p.id === persona)?.label ?? "";

  async function send(kind: "start" | "text" | "callback", opts: { text?: string; data?: string; label?: string; sourceId?: number } = {}) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
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
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 md:grid-cols-[minmax(0,18rem)_minmax(0,1fr)] md:items-start">
      <div className="flex flex-col gap-4">
        <div className="grid gap-1.5">
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

        <div className="grid gap-1.5">
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
        </div>

        <div className="flex flex-wrap gap-2">
          <Button onClick={() => send("start")} disabled={busy}>
            <Play />
            شروع
          </Button>
          <Button variant="outline" onClick={() => reset(revisionId)} disabled={busy}>
            <RotateCcw />
            بازنشانی
          </Button>
        </div>

        {error && <ErrorNote>{error}</ErrorNote>}
        {notice && <InfoNote tone="warning">{notice}</InfoNote>}
        <p className="text-sm leading-7 text-muted-foreground">
          این گفتگو فقط آزمایشی است و به تلگرام نمی‌رود. وقتی پیامی برای کاربر دیگری برسد (مثلاً اعلان ثبت‌نام برای مدیر)، روی نام او نشانگر می‌بینید.
        </p>
      </div>

      <PhoneFrame
        botName={bot.name}
        personaLabel={personaLabel}
        items={conv.chats[persona]}
        busy={busy}
        onPress={(item: ChatItem, b: RuntimeButton) => send("callback", { data: b.data, label: b.label, sourceId: item.id })}
        onSendText={(text) => send("text", { text })}
      />
    </div>
  );
}
