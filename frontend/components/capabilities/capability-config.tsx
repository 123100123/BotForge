"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import { AUDIENCE_LABELS, configLabel } from "@/components/capabilities/labels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ChoiceSelect, ToggleField } from "@/components/data/controls";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { CapabilityOut } from "@/lib/types";

type Draft = Record<string, string | boolean>;

/** The editable fields of a capability: module capabilities expose their simple `config` values, spec capabilities the audience and reminder hours. */
function initialDraft(cap: CapabilityOut): Draft {
  const draft: Draft = {};
  if (cap.kind === "spec" && cap.audience !== null) draft.audience = cap.audience;
  for (const [key, value] of Object.entries(cap.config)) {
    if (cap.kind === "spec" && key !== "reminder_hours_before") continue;
    if (typeof value === "number") draft[key] = String(value);
    else if (typeof value === "string" || typeof value === "boolean") draft[key] = value;
  }
  return draft;
}

export function hasConfigFields(cap: CapabilityOut): boolean {
  return Object.keys(initialDraft(cap)).length > 0;
}

/** Config form of one capability, saved with `updateCapabilityConfig`. Only changed fields are sent. */
export function CapabilityConfig({
  botId,
  cap,
  onSaved,
  onBusyChange,
}: {
  botId: string;
  cap: CapabilityOut;
  onSaved: (updated: CapabilityOut) => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [initial, setInitial] = useState(() => initialDraft(cap));
  const [draft, setDraft] = useState<Draft>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const feedback = useRef<HTMLDivElement>(null);
  useEffect(() => { if (!busy && (saved || error)) feedback.current?.focus(); }, [saved, error, busy]);

  const keys = Object.keys(initial);
  const changed = keys.filter((k) => draft[k] !== initial[k]);

  function set(key: string, value: string | boolean) {
    setDraft((d) => ({ ...d, [key]: value }));
    setSaved(false);
  }

  async function save() {
    const config: Record<string, unknown> = {};
    for (const key of changed) {
      const original = cap.config[key];
      if (typeof original === "number") {
        const n = Number(draft[key]);
        if (draft[key] === "" || !Number.isFinite(n) || n < 0) {
          setError(`مقدار «${configLabel(key)}» باید عددی بزرگ‌تر یا مساوی صفر باشد.`);
          return;
        }
        config[key] = n;
      } else {
        config[key] = draft[key];
      }
    }
    setBusy(true);
    onBusyChange?.(true);
    setError(null);
    try {
      onSaved(await api.updateCapabilityConfig(botId, cap.id, { config }));
      setInitial(draft);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {keys.map((key) => {
        const id = `cfg-${cap.id}-${key}`;
        const value = draft[key];
        if (key === "audience") {
          return (
            <div key={key} className="flex flex-col gap-1.5">
              <Label htmlFor={id}>چه کسانی می‌توانند از این قابلیت استفاده کنند؟</Label>
              <ChoiceSelect id={id} label="مخاطب قابلیت" isDisabled={busy} value={String(value)} onChange={(v) => set(key, v)} options={Object.entries(AUDIENCE_LABELS).map(([v, label]) => ({ value: v, label }))} />
            </div>
          );
        }
        if (typeof value === "boolean") {
          return (
            <div key={key} className="flex items-center justify-between gap-3">
              <ToggleField id={id} label={configLabel(key)} isDisabled={busy} value={value} onChange={(v) => set(key, v)} />
            </div>
          );
        }
        const numeric = typeof cap.config[key] === "number";
        return (
          <div key={key} className="flex flex-col gap-1.5">
            <Label htmlFor={id}>{configLabel(key)}</Label>
            <Input
              id={id}
              disabled={busy}
              value={String(value)}
              onChange={(e) => set(key, e.target.value)}
              type={numeric ? "number" : "text"}
              min={numeric ? 0 : undefined}
              inputMode={numeric ? "numeric" : undefined}
              dir={numeric ? "ltr" : undefined}
              className={numeric ? "max-w-32 text-start" : undefined}
            />
          </div>
        );
      })}
      {(error || saved) && <div ref={feedback} tabIndex={-1} className="rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-ring">{error ? <ErrorNote>{error}</ErrorNote> : <InfoNote>تنظیمات ذخیره شد.</InfoNote>}</div>}
      <Button variant="outline" size="sm" className="self-start" isDisabled={busy || changed.length === 0} onPress={save}>
        {busy ? "در حال ذخیره…" : "ذخیرهٔ تنظیمات"}
      </Button>
    </div>
  );
}
