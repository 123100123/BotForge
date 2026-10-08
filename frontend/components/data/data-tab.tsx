"use client";

import { useOpenSection } from "@/components/app/shell/use-open-section";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { EmptyState, ErrorNote, InfoNote, LoadingBlock } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { ApiError, ERROR_CODES, errorMessage } from "@/lib/errors";
import type { Bot, CollectionAction, DataCollection, DataRecord, RecordsPage } from "@/lib/types";
import { CollectionNav } from "./collection-nav";
import { RecordForm } from "./record-form";
import { RecordTable } from "./record-table";

const PAGE_SIZE = 10;

type Overview =
  | { state: "no_revision" }
  | { state: "error"; message: string }
  | { state: "ready"; collections: DataCollection[] };

/**
 * Records of the business's data collections. `collectionKeys` focuses it on some collections (an Operations
 * page: orders, events, one resource...), in that order; with one collection the collection list is hidden.
 * Without it every collection of the active revision is listed (the /records page).
 */
export function DataTab({ bot, collectionKeys }: { bot: Bot; collectionKeys?: string[] }) {
  const openSection = useOpenSection();
  /** `key` identifies the bot and active revision the overview was loaded for; a stale one counts as loading. */
  const [loaded, setLoaded] = useState<{ key: string; overview: Overview } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  /** Stable identity of the focus list (the array itself is a new one on every render of the page). */
  const scope = collectionKeys ? collectionKeys.join("\n") : null;
  const [counts, setCounts] = useState<Record<string, number>>({});
  /** Bumped after every change so the table and the counts reload. */
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // The collections come from the ACTIVE revision, so a new active revision reloads everything.
  const key = `${bot.id}:${bot.active_revision_id ?? ""}`;
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.getDataOverview(bot.id);
        if (cancelled) return;
        setLoaded({ key, overview: { state: "ready", collections: data.collections } });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === ERROR_CODES.noActiveRevision) setLoaded({ key, overview: { state: "no_revision" } });
        else setLoaded({ key, overview: { state: "error", message: errorMessage(err) } });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [bot.id, bot.active_revision_id, key]);

  const overview = loaded && loaded.key === key ? loaded.overview : null;
  const all = overview?.state === "ready" ? overview.collections : null;
  const collections = useMemo(() => {
    if (!all || scope === null) return all;
    const byKey = new Map(all.map((c) => [c.key, c]));
    return scope
      .split("\n")
      .map((k) => byKey.get(k))
      .filter((c): c is DataCollection => c !== undefined);
  }, [all, scope]);
  useEffect(() => {
    if (!collections || collections.length <= 1) return;
    let cancelled = false;
    Promise.all(
      collections.map((c) =>
        api.listRecords(bot.id, c.key, { limit: 1 }).then(
          (p) => [c.key, p.total] as const,
          () => null,
        ),
      ),
    ).then((entries) => {
      if (cancelled) return;
      const next: Record<string, number> = {};
      for (const e of entries) if (e) next[e[0]] = e[1];
      setCounts(next);
    });
    return () => {
      cancelled = true;
    };
  }, [bot.id, collections, tick]);

  if (!overview) return <LoadingBlock />;
  if (overview.state === "no_revision") {
    return (
      <EmptyState
        title="هنوز داده‌ای وجود ندارد"
        action={
          <Button variant="outline" onClick={() => openSection("changes")}>
            رفتن به تغییرات
          </Button>
        }
      >
        این ربات هنوز نسخهٔ فعالی ندارد. ابتدا در «تغییرات» ربات را بسازید و تأیید کنید؛ بعد می‌توانید موارد آن (مثل کارگاه‌ها) را اینجا اضافه کنید.
      </EmptyState>
    );
  }
  if (overview.state === "error") return <ErrorNote>{overview.message}</ErrorNote>;

  const shown = collections ?? [];
  const current = shown.find((c) => c.key === selected) ?? shown[0] ?? null;
  return (
    <div className="flex flex-col gap-5 md:flex-row md:items-start">
      {shown.length > 1 && <CollectionNav collections={shown} selected={current?.key ?? null} counts={counts} onSelect={setSelected} />}
      <div className="min-w-0 flex-1">
        {current ? (
          <CollectionPanel
            key={current.key}
            botId={bot.id}
            collection={current}
            tick={tick}
            onChanged={refresh}
          />
        ) : (
          <EmptyState title="مجموعه‌ای وجود ندارد">این نسخهٔ ربات داده‌ای برای مدیریت ندارد.</EmptyState>
        )}
      </div>
    </div>
  );
}

interface PanelProps {
  botId: string;
  collection: DataCollection;
  tick: number;
  onChanged: () => void;
}

function CollectionPanel({ botId, collection, tick, onChanged }: PanelProps) {
  const [offset, setOffset] = useState(0);
  const [loaded, setLoaded] = useState<RecordsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<DataRecord | null>(null);
  const [deleting, setDeleting] = useState<DataRecord | null>(null);
  const [cancelling, setCancelling] = useState<{ record: DataRecord; action: CollectionAction } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await api.listRecords(botId, collection.key, { limit: PAGE_SIZE, offset });
        if (cancelled) return;
        // Past the last page after a deletion: step back.
        if (page.items.length === 0 && offset > 0 && page.total > 0) {
          setOffset(Math.max(0, (Math.ceil(page.total / PAGE_SIZE) - 1) * PAGE_SIZE));
          return;
        }
        setLoaded(page);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [botId, collection.key, offset, tick]);

  async function runAction(record: DataRecord, action: string) {
    const res = await api.runRecordAction(botId, collection.key, record.id, action);
    setResult({ ok: res.ok, message: res.message });
    onChanged();
  }

  const titleOf = (r: DataRecord) => r.item_title ?? "این مورد";
  // Orders are placed by customers in Telegram; the web never creates them.
  const writable = collection.writable && collection.kind !== "orders";

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">{collection.label_plural}</CardTitle>
        {writable && (
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            <Plus />
            افزودن {collection.label}
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {result && <InfoNote tone={result.ok ? "success" : "warning"}>{result.message}</InfoNote>}
        {error && <ErrorNote>{error}</ErrorNote>}
        {!loaded && !error && <LoadingBlock />}
        {loaded && loaded.total === 0 && (
          <p className="rounded-md border border-dashed p-8 text-center text-sm leading-7 text-muted-foreground">
            {writable
              ? `هنوز ${collection.label} اضافه نشده است. با دکمهٔ «افزودن ${collection.label}» شروع کنید.`
              : "هنوز موردی ثبت نشده است. وقتی مشتری‌ها از ربات استفاده کنند، اینجا نمایش داده می‌شود."}
          </p>
        )}
        {loaded && loaded.total > 0 && (
          <RecordTable
            collection={collection}
            records={loaded.items}
            total={loaded.total}
            offset={loaded.offset}
            limit={loaded.limit}
            onPage={setOffset}
            onEdit={(r) => {
              setEditing(r);
              setFormOpen(true);
            }}
            onDelete={setDeleting}
            onAction={(r: DataRecord, a: CollectionAction) => {
              if (collection.kind === "booking") {
                setCancelling({ record: r, action: a }); // cancelling a booking asks first
                return;
              }
              setResult(null);
              runAction(r, a.key).catch((err) => setResult({ ok: false, message: errorMessage(err) }));
            }}
          />
        )}
      </CardContent>

      {writable && (
        <RecordForm
          botId={botId}
          collection={collection}
          record={editing}
          open={formOpen}
          onOpenChange={setFormOpen}
          onSaved={() => {
            setResult(null);
            onChanged();
          }}
        />
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`حذف ${collection.label}`}
        description="این مورد برای همیشه حذف می‌شود و از ربات هم برداشته می‌شود."
        confirmLabel="حذف"
        destructive
        onConfirm={async () => {
          if (!deleting) return;
          setResult(null);
          await api.deleteRecord(botId, collection.key, deleting.id);
          onChanged();
        }}
      />

      <ConfirmDialog
        open={cancelling !== null}
        onOpenChange={(o) => !o && setCancelling(null)}
        title="لغو ثبت‌نام"
        description={
          cancelling
            ? `ثبت‌نام این مشتری در «${titleOf(cancelling.record)}» لغو شود؟ اگر نفر دیگری در لیست انتظار باشد، جایگزین می‌شود و به او در تلگرام اطلاع داده می‌شود.`
            : ""
        }
        confirmLabel={cancelling?.action.label ?? "لغو ثبت‌نام"}
        destructive
        onConfirm={async () => {
          if (!cancelling) return;
          setResult(null);
          await runAction(cancelling.record, cancelling.action.key);
        }}
      />
    </Card>
  );
}
