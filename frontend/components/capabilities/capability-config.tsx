"use client";

import { useState } from "react";
import { ErrorNote, InfoNote } from "@/components/app/state-blocks";
import { AUDIENCE_LABELS, configLabel } from "@/components/capabilities/labels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
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
}: {
  botId: string;
  cap: CapabilityOut;
  onSaved: (updated: CapabilityOut) => void;
}) {
  const [initial, setInitial] = useState(() => initialDraft(cap));
  const [draft, setDraft] = useState<Draft>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

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
    setError(null);
    try {
      onSaved(await api.updateCapabilityConfig(botId, cap.id, { config }));
      setInitial(draft);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
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
              <Select id={id} value={String(value)} onChange={(e) => set(key, e.target.value)}>
                {Object.entries(AUDIENCE_LABELS).map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </Select>
            </div>
          );
        }
        if (typeof value === "boolean") {
          return (
            <div key={key} className="flex items-center justify-between gap-3">
              <Label htmlFor={id}>{configLabel(key)}</Label>
              <Switch id={id} checked={value} onCheckedChange={(v) => set(key, v)} />
            </div>
          );
        }
        const numeric = typeof cap.config[key] === "number";
        return (
          <div key={key} className="flex flex-col gap-1.5">
            <Label htmlFor={id}>{configLabel(key)}</Label>
            <Input
              id={id}
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
      {error && <ErrorNote>{error}</ErrorNote>}
      {saved && <InfoNote>تنظیمات ذخیره شد.</InfoNote>}
      <Button variant="secondary" size="sm" className="self-start" disabled={busy || changed.length === 0} onClick={save}>
        {busy ? "در حال ذخیره…" : "ذخیرهٔ تنظیمات"}
      </Button>
    </div>
  );
}
