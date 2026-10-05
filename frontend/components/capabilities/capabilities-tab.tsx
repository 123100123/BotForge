"use client";

import { useMemo, useState } from "react";
import { EmptyState, ErrorNote, InfoNote, LoadingBlock } from "@/components/app/state-blocks";
import { useLoader } from "@/components/app/use-loader";
import type { WorkspaceTab } from "@/components/app/workspace";
import { CapabilityCard } from "@/components/capabilities/capability-card";
import { CapabilityDialog, type ToggleSuccess } from "@/components/capabilities/capability-dialog";
import { openSection } from "@/components/capabilities/labels";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { Bot, CapabilityListOut, CapabilityOut } from "@/lib/types";

/**
 * Capability Center: every capability of the business, grouped by category, with its on/off state.
 * A click opens the detail panel, where the owner previews and confirms a toggle.
 * `onOpenTab` and `onBotChanged` are optional: without `onOpenTab` the tab links activate the sidebar trigger.
 */
export function CapabilitiesTab({
  bot,
  onOpenTab,
  onBotChanged,
}: {
  bot: Bot;
  onOpenTab?: (tab: WorkspaceTab) => void;
  onBotChanged?: () => void;
}) {
  const { data, error } = useLoader(() => api.listCapabilities(bot.id), bot.id);
  // A list re-read after a toggle replaces the loaded one (without flashing the loading state).
  const [fresh, setFresh] = useState<{ botId: string; list: CapabilityListOut } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [success, setSuccess] = useState<ToggleSuccess | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const list = fresh && fresh.botId === bot.id ? fresh.list : data;
  const all = useMemo(() => (list ? list.categories.flatMap((c) => c.capabilities) : []), [list]);
  const byId = useMemo(() => new Map(all.map((c) => [c.id, c])), [all]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!list) return <LoadingBlock />;

  const categories = list.categories.filter((c) => c.capabilities.length > 0);
  if (categories.length === 0) {
    return (
      <EmptyState title="قابلیتی در دسترس نیست">
        فهرست قابلیت‌های کسب‌وکار پس از ساخت ربات اینجا نمایش داده می‌شود.
      </EmptyState>
    );
  }

  const enabledCount = all.filter((c) => c.enabled).length;
  const selected: CapabilityOut | undefined = selectedId ? byId.get(selectedId) : undefined;

  async function refresh() {
    try {
      setFresh({ botId: bot.id, list: await api.listCapabilities(bot.id) });
      setRefreshError(null);
    } catch (err) {
      setRefreshError(errorMessage(err));
    }
  }

  function patchCapability(updated: CapabilityOut) {
    setFresh({
      botId: bot.id,
      list: {
        categories: list!.categories.map((c) => ({
          ...c,
          capabilities: c.capabilities.map((x) => (x.id === updated.id ? updated : x)),
        })),
      },
    });
  }

  async function handleToggled(result: ToggleSuccess) {
    setSelectedId(null);
    setSuccess(result);
    await refresh();
    onBotChanged?.();
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h2 className="text-lg font-bold">مرکز قابلیت‌ها</h2>
        <p className="text-sm leading-7 text-muted-foreground">
          <span className="font-semibold text-foreground">
            {fa(enabledCount)} قابلیت فعال از {fa(all.length)}
          </span>
          {" · "}
          هر قابلیت را روشن یا خاموش کنید؛ پیش از هر تغییر، اثر آن را می‌بینید.
        </p>
      </header>

      {success && (
        <InfoNote className="flex flex-wrap items-center justify-between gap-2">
          <span>
            {success.capabilityName} {success.action === "enable" ? "فعال" : "غیرفعال"} شد.
            {success.revisionNumber !== null && ` نسخهٔ ${fa(success.revisionNumber)} ساخته و فعال شد.`}
          </span>
          {success.revisionNumber !== null && (
            <Button variant="link" size="sm" className="h-auto p-0" onClick={() => openSection("versions", onOpenTab)}>
              مشاهدهٔ نسخه‌ها
            </Button>
          )}
        </InfoNote>
      )}
      {refreshError && <ErrorNote>{refreshError}</ErrorNote>}

      {categories.map((category) => (
        <section key={category.id} aria-label={category.name} className="flex flex-col gap-3">
          <h3 className="text-base font-semibold">{category.name}</h3>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {category.capabilities.map((c) => (
              <CapabilityCard key={c.id} cap={c} byId={byId} onOpen={() => setSelectedId(c.id)} />
            ))}
          </div>
        </section>
      ))}

      {selected && (
        <CapabilityDialog
          key={selected.id}
          botId={bot.id}
          cap={selected}
          byId={byId}
          onClose={() => setSelectedId(null)}
          onCapabilityUpdated={patchCapability}
          onToggled={handleToggled}
          onOpenTab={onOpenTab}
        />
      )}
    </div>
  );
}
