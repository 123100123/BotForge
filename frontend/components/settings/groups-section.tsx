"use client";

import { useEffect, useMemo, useState } from "react";
import { Megaphone, MessagesSquare } from "lucide-react";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/format";
import type { DataCollection, DataRecord, GroupOut } from "@/lib/types";
import { ConfirmDialog } from "./confirm-dialog";

const KIND_LABELS: Record<GroupOut["kind"], string> = { group: "گروه", supergroup: "سوپرگروه", channel: "کانال" };

function recordTitle(rec: DataRecord, col: DataCollection | undefined): string {
  const fromField = col?.title_field ? rec.data[col.title_field] : undefined;
  const candidate = fromField ?? rec.item_title ?? rec.data.title ?? rec.data.name;
  return typeof candidate === "string" && candidate.trim() ? candidate : `رکورد ${rec.id}`;
}

/** The groups the bot was added to, with a publish action that posts an event card to a group. */
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessagesSquare className="size-5 text-muted-foreground" />
          گروه‌ها
        </CardTitle>
        <CardDescription>گروه‌ها و کانال‌هایی که ربات به آن‌ها اضافه شده است؛ می‌توانید کارت یک رویداد را در آن‌ها منتشر کنید.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error && <ErrorNote>{error}</ErrorNote>}
        {!groups ? (
          !error && <div role="status" aria-label="در حال بارگذاری" className="h-20 animate-pulse rounded-md bg-border" />
        ) : groups.length === 0 ? (
          <p className="text-sm leading-7 text-muted-foreground">
            هنوز ربات در هیچ گروهی نیست. در تلگرام وارد گروه یا کانال خود شوید، ربات را از بخش افزودن عضو اضافه کنید (برای کانال، ربات باید
            مدیر باشد) و بعد این صفحه را دوباره باز کنید.
          </p>
        ) : (
          <ul className="flex flex-col divide-y rounded-sm border">
            {groups.map((g) => (
              <li key={g.chat_id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="truncate text-sm font-medium">{g.title}</span>
                  <span className="text-caption text-muted-foreground">
                    {KIND_LABELS[g.kind]} · اضافه‌شده در {formatDate(g.added_at)}
                  </span>
                </div>
                <Badge variant={g.active ? "success" : "secondary"}>{g.active ? "فعال" : "غیرفعال"}</Badge>
                <Button variant="outline" size="sm" disabled={!g.active} onClick={() => setPublishing(g)}>
                  <Megaphone />
                  انتشار رویداد
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {publishing && <PublishDialog botId={botId} group={publishing} collections={collections} onClose={() => setPublishing(null)} />}
    </Card>
  );
}

function PublishDialog({
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
  const [done, setDone] = useState<string | null>(null);

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
      setDone(out.message || "در صف ارسال قرار گرفت.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      setStep("pick");
    }
  }

  const title = chosen && col ? recordTitle(chosen, col) : "";
  const confirming = step === "confirm" && !!chosen;

  if (done) {
    return (
      <ConfirmDialog
        open
        title="انتشار رویداد"
        description={`در «${group.title}»`}
        confirmLabel="بستن"
        hideCancel
        onConfirm={onClose}
        onCancel={onClose}
      >
        <InfoNote>{done}</InfoNote>
      </ConfirmDialog>
    );
  }

  if (confirming) {
    return (
      <ConfirmDialog
        open
        title="انتشار در گروه؟"
        description={`کارت «${title}» در «${group.title}» ارسال می‌شود و همهٔ اعضای گروه آن را می‌بینند.`}
        confirmLabel="انتشار"
        busy={busy}
        onConfirm={publish}
        onCancel={() => setStep("pick")}
      />
    );
  }

  return (
    <ConfirmDialog
      open
      title="انتشار رویداد"
      description={`کارت یک رویداد را در «${group.title}» منتشر کنید.`}
      confirmLabel="ادامه"
      confirmDisabled={!chosen}
      onConfirm={() => setStep("confirm")}
      onCancel={onClose}
    >
      <div className="flex flex-col gap-3">
        {error && <ErrorNote>{error}</ErrorNote>}
        {candidates.length === 0 ? (
          <p className="text-sm leading-7 text-muted-foreground">برای انتشار باید حداقل یک مجموعهٔ داده (مثلاً رویدادها) داشته باشید.</p>
        ) : (
          <>
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
                <div className="h-9 animate-pulse rounded-sm bg-border" role="status" aria-label="در حال بارگذاری" />
              ) : items.length === 0 ? (
                <p className="text-sm leading-7 text-muted-foreground">این مجموعه هنوز رکوردی ندارد.</p>
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
          </>
        )}
      </div>
    </ConfirmDialog>
  );
}
