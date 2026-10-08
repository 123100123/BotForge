"use client";

import { useEffect, useState } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { GroupOut } from "@/lib/types";

/**
 * Posts one event's card to a Telegram group the bot is in. `resourceKey` is the events resource
 * (the backend looks the card up by the resource that the events capability books).
 */
export function PublishEventDialog({
  botId,
  resourceKey,
  eventId,
  eventTitle,
  onClose,
}: {
  botId: string;
  resourceKey: string;
  eventId: number | null;
  eventTitle: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={eventId !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        {eventId !== null && <PublishBody botId={botId} resourceKey={resourceKey} eventId={eventId} eventTitle={eventTitle} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function PublishBody({ botId, resourceKey, eventId, eventTitle, onClose }: { botId: string; resourceKey: string; eventId: number; eventTitle: string; onClose: () => void }) {
  const [groups, setGroups] = useState<GroupOut[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.listGroups(botId).then(
      (g) => {
        if (cancelled) return;
        const active = g.filter((x) => x.active);
        setGroups(active);
        setPicked(active[0] ? String(active[0].chat_id) : "");
      },
      (err) => !cancelled && setLoadError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);

  const group = groups?.find((g) => String(g.chat_id) === picked);

  async function publish() {
    if (!group) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.publishToGroup(botId, group.chat_id, { collection: resourceKey, record_id: eventId });
      toast({ title: out.message || "کارت رویداد در صف ارسال قرار گرفت.", description: `گروه: ${group.title}`, tone: out.queued ? "success" : "neutral" });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>انتشار در گروه</DialogTitle>
        <DialogDescription>
          کارت «{eventTitle}» با دکمهٔ ثبت‌نام در گروه انتخاب‌شده فرستاده می‌شود و همهٔ اعضای گروه آن را می‌بینند.
        </DialogDescription>
      </DialogHeader>
      {loadError ? (
        <ErrorNote>{loadError}</ErrorNote>
      ) : groups === null ? (
        <Skeleton aria-label="در حال بارگذاری گروه‌ها" role="status" className="h-10 rounded-sm" />
      ) : groups.length === 0 ? (
        <p className="text-small text-fg-secondary">
          ربات هنوز در هیچ گروه فعالی نیست. ربات را در تلگرام به گروه یا کانال اضافه کنید (برای کانال، ربات باید مدیر باشد) و دوباره تلاش کنید.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="publish-group">گروه</Label>
          <Select id="publish-group" value={picked} onChange={(e) => setPicked(e.target.value)}>
            {groups.map((g) => (
              <option key={g.chat_id} value={g.chat_id}>
                {g.title}
              </option>
            ))}
          </Select>
        </div>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      <DialogFooter>
        <Button onClick={publish} loading={busy} disabled={!group}>
          انتشار
        </Button>
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          انصراف
        </Button>
      </DialogFooter>
    </>
  );
}
