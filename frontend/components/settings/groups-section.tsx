"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleCheck, CircleSlash, Megaphone, MessagesSquare } from "lucide-react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/use-toast";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa, formatDate } from "@/lib/format";
import type { DataCollection, DataRecord, GroupOut } from "@/lib/types";
import { SettingsPanel } from "./settings-panel";

const KIND_LABELS: Record<GroupOut["kind"], string> = { group: "گروه", supergroup: "سوپرگروه", channel: "کانال" };

function recordTitle(rec: DataRecord, col: DataCollection | undefined): string {
  const fromField = col?.title_field ? rec.data[col.title_field] : undefined;
  const candidate = fromField ?? rec.item_title ?? rec.data.title ?? rec.data.name;
  return typeof candidate === "string" && candidate.trim() ? candidate : `رکورد ${rec.id}`;
}

/** The groups and channels the bot is a member of, with a publish action that posts an event card to a group. */
export function GroupsSection({ botId }: { botId: string }) {
  const [groups, setGroups] = useState<GroupOut[] | null>(null);
  const [collections, setCollections] = useState<DataCollection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState<GroupOut | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.listGroups(botId).then(
      (g) => !cancelled && setGroups(g),
      (err) => !cancelled && setError(errorMessage(err)),
    );
    // Only the publish dialog needs the collections; a failure there is shown inside the dialog.
    api.getDataOverview(botId).then(
      (o) => !cancelled && setCollections(o.collections),
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);

  return (
    <SettingsPanel
      title="گروه‌ها و کانال‌ها"
      description="گروه‌ها و کانال‌هایی که ربات عضو آن‌هاست. می‌توانید کارت یک رویداد را در آن‌ها منتشر کنید."
    >
      {error && (
        <div className="border-t border-border p-5">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
      {!groups ? (
        !error && (
          <div role="status" aria-label="در حال بارگذاری" className="border-t border-border p-5">
            <Skeleton className="h-16 rounded-sm" />
          </div>
        )
      ) : groups.length === 0 ? (
        <div className="border-t border-border">
          <EmptyState
            icon={<MessagesSquare strokeWidth={1.75} />}
            title="ربات هنوز در هیچ گروه یا کانالی نیست"
            description="برای افزودن، در تلگرام وارد گروه یا کانال خود شوید و ربات را از بخش افزودن عضو اضافه کنید. در کانال، ربات باید مدیر (administrator) باشد. بعد این صفحه را دوباره باز کنید."
          />
        </div>
      ) : (
        <ul className="flex flex-col">
          {groups.map((g) => (
            <li key={g.chat_id} className="flex flex-wrap items-center gap-x-4 gap-y-3 border-t border-border px-5 py-4">
              <div className="flex min-w-0 flex-1 basis-56 flex-col gap-0.5">
                <span className="truncate text-body font-medium text-fg">{g.title}</span>
                <span className="text-small text-fg-muted">
                  {KIND_LABELS[g.kind]} · اضافه‌شده در {formatDate(g.added_at)}
                </span>
              </div>
              {g.active ? (
                <StatusBadge tone="success" icon={<CircleCheck strokeWidth={1.75} aria-hidden />}>
                  فعال
                </StatusBadge>
              ) : (
                <StatusBadge tone="neutral" icon={<CircleSlash strokeWidth={1.75} aria-hidden />}>
                  غیرفعال
                </StatusBadge>
              )}
              <Button variant="secondary" size="sm" disabled={!g.active} onClick={() => setPublishing(g)}>
                <Megaphone strokeWidth={1.75} />
                انتشار رویداد
              </Button>
            </li>
          ))}
          <li className="border-t border-border px-5 py-3 text-small text-fg-muted">
            {fa(groups.length)} گروه یا کانال. تاریخچهٔ انتشارها هنوز در دسترس نیست.
          </li>
        </ul>
      )}
      {publishing && <PublishDialog botId={botId} group={publishing} collections={collections} onClose={() => setPublishing(null)} />}
    </SettingsPanel>
  );
}

/** Publishes the card of an event (record) to a group in three steps inside one dialog: pick, confirm, result. */
export function PublishDialog({
  botId,
  group,
  collections,
  onClose,
}: {
  botId: string;
  group: GroupOut;
  collections: DataCollection[];
  onClose: () => void;
}) {
  // Events live in a booking collection when one exists; otherwise let the owner choose among all.
  const candidates = useMemo(() => {
    const booking = collections.filter((c) => c.kind === "booking");
    return booking.length > 0 ? booking : collections;
  }, [collections]);

  const [picked, setPicked] = useState("");
  // Falls back to the first candidate, which may arrive after the dialog opened.
  const collection = candidates.some((c) => c.key === picked) ? picked : (candidates[0]?.key ?? "");
  const [records, setRecords] = useState<{ key: string; items: DataRecord[] } | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [recordId, setRecordId] = useState("");
  const [step, setStep] = useState<"pick" | "confirm">("pick");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const col = candidates.find((c) => c.key === collection);

  useEffect(() => {
    if (!collection) return;
    let cancelled = false;
    api.listRecords(botId, collection, { limit: 50 }).then(
      (page) => {
        if (cancelled) return;
        setRecords({ key: collection, items: page.items });
        setRecordError(null);
        setRecordId(page.items[0] ? String(page.items[0].id) : "");
      },
      (err) => !cancelled && setRecordError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [botId, collection]);

  const items = records && records.key === collection ? records.items : null;
  const chosen = items?.find((r) => String(r.id) === recordId);

  async function publish() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.publishToGroup(botId, group.chat_id, { collection, record_id: chosen.id });
      toast({ title: out.message || "کارت رویداد در صف ارسال قرار گرفت.", description: `گروه: ${group.title}`, tone: "success" });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
      setStep("pick");
    }
  }

  const title = chosen && col ? recordTitle(chosen, col) : "";
  const confirming = step === "confirm" && !!chosen;
  const lead = confirming
    ? `کارت «${title}» با دکمهٔ ثبت‌نام در «${group.title}» فرستاده می‌شود و همهٔ اعضای گروه آن را می‌بینند.`
    : `کارت یک رویداد را در «${group.title}» منتشر کنید.`;

  return (
    <Dialog open onOpenChange={(next) => !next && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>انتشار در گروه</DialogTitle>
          <DialogDescription>{lead}</DialogDescription>
        </DialogHeader>

        {error && <ErrorNote>{error}</ErrorNote>}
        {!confirming &&
          (candidates.length === 0 ? (
            <p className="text-small text-fg-secondary">برای انتشار باید حداقل یک مجموعهٔ داده (مثلاً رویدادها) داشته باشید.</p>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="publish-collection">مجموعه</Label>
                <Select id="publish-collection" value={collection} onChange={(e) => setPicked(e.target.value)}>
                  {candidates.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label_plural || c.label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="publish-record">رویداد</Label>
                {recordError ? (
                  <ErrorNote>{recordError}</ErrorNote>
                ) : !items ? (
                  <Skeleton className="h-10 rounded-sm" />
                ) : items.length === 0 ? (
                  <p className="text-small text-fg-secondary">این مجموعه هنوز رکوردی ندارد.</p>
                ) : (
                  <Select id="publish-record" value={recordId} onChange={(e) => setRecordId(e.target.value)}>
                    {items.map((r) => (
                      <option key={r.id} value={r.id}>
                        {recordTitle(r, col)}
                      </option>
                    ))}
                  </Select>
                )}
              </div>
            </div>
          ))}

        <DialogFooter>
          {confirming ? (
            <>
              <Button onClick={() => void publish()} loading={busy}>
                انتشار
              </Button>
              <Button variant="secondary" onClick={() => setStep("pick")} disabled={busy}>
                انصراف
              </Button>
            </>
          ) : (
            <>
              <Button onClick={() => setStep("confirm")} disabled={!chosen}>
                ادامه
              </Button>
              <Button variant="secondary" onClick={onClose}>
                انصراف
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
