"use client";

import { useState } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToggleField } from "@/components/data/controls";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { AnalysisProfileOut } from "@/lib/types";
import { CHECK_LABELS, MEASURE_LABELS, parseNumberInput } from "./labels";

/** Text shown in a number field: Persian digits, empty for null. */
function numText(n: number | null): string {
  return n === null ? "" : fa(n);
}

/** Simple editor: profile name, daily flag, metric labels and top-N, check labels and thresholds. */
export function ProfileEditDialog({
  botId,
  profile,
  onClose,
  onSaved,
}: {
  botId: string;
  profile: AnalysisProfileOut;
  onClose: () => void;
  onSaved: (profile: AnalysisProfileOut) => void;
}) {
  const [name, setName] = useState(profile.name);
  const [daily, setDaily] = useState(profile.daily_report);
  const [metricLabels, setMetricLabels] = useState(() => (profile.metrics ?? []).map((m) => m.label));
  const [topNs, setTopNs] = useState(() => (profile.metrics ?? []).map((m) => numText(m.top_n)));
  const [checkLabels, setCheckLabels] = useState(() => (profile.checks ?? []).map((c) => c.label));
  const [thresholds, setThresholds] = useState(() => (profile.checks ?? []).map((c) => numText(c.threshold)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const metrics = profile.metrics ?? [];
  const checks = profile.checks ?? [];

  function setAt(setter: React.Dispatch<React.SetStateAction<string[]>>, index: number, value: string) {
    setter((prev) => prev.map((v, i) => (i === index ? value : v)));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("نام پروفایل را وارد کنید.");
      return;
    }
    for (let i = 0; i < metrics.length; i++) {
      const raw = topNs[i].trim();
      const n = parseNumberInput(raw);
      if (raw && (n === null || !Number.isInteger(n) || n < 1)) {
        setError(`تعداد برترین‌ها برای «${metricLabels[i]}» باید یک عدد صحیح مثبت باشد.`);
        return;
      }
    }
    for (let i = 0; i < checks.length; i++) {
      const raw = thresholds[i].trim();
      if (raw && parseNumberInput(raw) === null) {
        setError(`آستانهٔ «${checkLabels[i]}» باید عدد باشد.`);
        return;
      }
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await api.updateAnalysisProfile(botId, profile.id, {
        name: name.trim(),
        daily_report: daily,
        metrics: metrics.map((m, i) => ({
          ...m,
          label: metricLabels[i].trim() || m.label,
          top_n: parseNumberInput(topNs[i]),
        })),
        checks: checks.map((c, i) => ({
          ...c,
          label: checkLabels[i].trim() || c.label,
          threshold: parseNumberInput(thresholds[i]),
        })),
      });
      onSaved(saved);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
      <Modal.Backdrop isOpen onOpenChange={(open) => !open && !busy && onClose()} isDismissable={!busy} isKeyboardDismissDisabled={busy}>
        <Modal.Container size="lg" scroll="inside" className="max-h-[88dvh]">
          <Modal.Dialog className="max-h-[88dvh] overflow-y-auto">
        <form onSubmit={save} className="grid gap-4">
          <Modal.Header>
            <Modal.Heading>ویرایش پروفایل</Modal.Heading>
            <p className="text-sm leading-7 text-muted-foreground">نام شاخص‌ها و آستانهٔ بررسی‌ها را تغییر دهید. ستون‌ها و روش محاسبه ثابت می‌مانند.</p>
          </Modal.Header>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pe-name">نام پروفایل</Label>
            <Input id="pe-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} disabled={busy} />
          </div>
          <div className="flex items-center gap-2">
            <ToggleField id="pe-daily" label="گزارش روزانهٔ کارکنان" value={daily} onChange={setDaily} isDisabled={busy} />
          </div>

          {metrics.length > 0 && (
            <fieldset className="grid gap-3">
              <legend className="mb-1 text-sm font-semibold">شاخص‌ها</legend>
              {metrics.map((m, i) => (
                <div key={m.id} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-[1fr_7rem]">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`pe-m-${m.id}`}>
                      {MEASURE_LABELS[m.measure] ?? m.measure}
                      {m.field && (
                        <span className="text-muted-foreground">
                          {" "}
                          <bdi>{m.field}</bdi>
                        </span>
                      )}
                    </Label>
                    <Input
                      id={`pe-m-${m.id}`}
                      value={metricLabels[i]}
                      onChange={(e) => setAt(setMetricLabels, i, e.target.value)}
                      disabled={busy}
                    />
                  </div>
                  {m.group_by && (
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`pe-n-${m.id}`}>برترین‌ها</Label>
                      <Input
                        id={`pe-n-${m.id}`}
                        inputMode="numeric"
                        value={topNs[i]}
                        onChange={(e) => setAt(setTopNs, i, e.target.value)}
                        placeholder="همه"
                        disabled={busy}
                      />
                    </div>
                  )}
                </div>
              ))}
            </fieldset>
          )}

          {checks.length > 0 && (
            <fieldset className="grid gap-3">
              <legend className="mb-1 text-sm font-semibold">بررسی‌ها</legend>
              {checks.map((c, i) => (
                <div key={c.id} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-[1fr_7rem]">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`pe-c-${c.id}`}>
                      {CHECK_LABELS[c.kind] ?? c.kind}
                      <span className="text-muted-foreground">
                        {" "}
                        <bdi>{c.field}</bdi>
                      </span>
                    </Label>
                    <Input
                      id={`pe-c-${c.id}`}
                      value={checkLabels[i]}
                      onChange={(e) => setAt(setCheckLabels, i, e.target.value)}
                      disabled={busy}
                    />
                  </div>
                  {c.kind !== "missing_values" && (
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`pe-t-${c.id}`}>آستانه</Label>
                      <Input
                        id={`pe-t-${c.id}`}
                        inputMode="decimal"
                        value={thresholds[i]}
                        onChange={(e) => setAt(setThresholds, i, e.target.value)}
                        placeholder="خودکار"
                        disabled={busy}
                      />
                    </div>
                  )}
                </div>
              ))}
            </fieldset>
          )}

          {error && <ErrorNote>{error}</ErrorNote>}
          <Modal.Footer className="flex flex-wrap gap-2">
            <Button type="submit" isDisabled={busy}>
              {busy ? "در حال ذخیره…" : "ذخیره"}
            </Button>
            <Button type="button" variant="outline" onPress={onClose} isDisabled={busy}>
              انصراف
            </Button>
          </Modal.Footer>
        </form>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
  );
}
