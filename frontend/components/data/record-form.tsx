"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { ApiError, ERROR_CODES, errorMessage } from "@/lib/errors";
import { toFaDigits } from "@/lib/format";
import type { DataCollection, DataRecord, FieldDef } from "@/lib/types";
import { initialValues, splitFieldErrors, toPayload, type FormValue, type FormValues } from "./field-utils";
import { JalaliDateTimeInput } from "./jalali-datetime-input";

interface RecordFormProps {
  botId: string;
  collection: DataCollection;
  /** The record being edited, or null to create one. */
  record: DataRecord | null;
  onCancel: () => void;
  onSaved: () => void;
}

/**
 * Create or edit form of a resource collection. It renders inside a RecordDrawer (the drawer owns the title);
 * mount it fresh for every open so the state starts clean.
 */
export function RecordForm({ botId, collection, record, onCancel: onClose, onSaved }: RecordFormProps) {
  const fields = collection.fields;
  const [values, setValues] = useState<FormValues>(() => initialValues(fields, record?.data));
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [generalErrors, setGeneralErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const set = (key: string, value: FormValue) => {
    setValues((v) => ({ ...v, [key]: value }));
    setFieldErrors((e) => {
      if (!e[key]) return e;
      const { [key]: removed, ...rest } = e;
      void removed;
      return rest;
    });
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setFieldErrors({});
    setGeneralErrors([]);
    try {
      const data = toPayload(fields, values);
      if (record) await api.updateRecord(botId, collection.key, record.id, data);
      else await api.createRecord(botId, collection.key, data);
      onSaved();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === ERROR_CODES.invalidRecord) {
        const { byField, general } = splitFieldErrors(fields, err);
        setFieldErrors(byField);
        setGeneralErrors(general.length > 0 || Object.keys(byField).length > 0 ? general : [err.message]);
      } else {
        setGeneralErrors([errorMessage(err)]);
      }
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-4">
      <p className="text-small text-fg-muted">
        {record ? "تغییرات بلافاصله در ربات اعمال می‌شود." : "پس از ذخیره، این مورد بلافاصله در ربات نمایش داده می‌شود."}
      </p>

      {fields.map((f) => (
        <FieldInput
          key={f.key}
          field={f}
          value={values[f.key]}
          error={fieldErrors[f.key]}
          timeZone={collection.timezone}
          onChange={(v) => set(f.key, v)}
        />
      ))}

      {generalErrors.length > 0 && (
        <div className="flex flex-col gap-2">
          {generalErrors.map((m, i) => (
            <p key={i} role="alert" className="rounded-sm bg-danger-soft p-3 text-small text-danger-text">
              {m}
            </p>
          ))}
        </div>
      )}

      <div className="flex flex-row-reverse justify-start gap-2">
        <Button type="submit" loading={saving}>
          {saving ? "در حال ذخیره…" : "ذخیره"}
        </Button>
        <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
          انصراف
        </Button>
      </div>
    </form>
  );
}

function FieldInput({
  field,
  value,
  error,
  timeZone,
  onChange,
}: {
  field: FieldDef;
  timeZone?: string;
  value: FormValue;
  error?: string;
  onChange: (value: FormValue) => void;
}) {
  const id = `field-${field.key}`;
  const errId = `${id}-error`;
  const invalid = Boolean(error);
  const str = typeof value === "string" ? value : "";
  const common = { id, "aria-invalid": invalid || undefined, "aria-describedby": invalid ? errId : undefined };

  let control;
  switch (field.type) {
    case "long_text":
      control = <Textarea {...common} value={str} rows={3} onChange={(e) => onChange(e.target.value)} />;
      break;
    case "integer":
    case "decimal":
      control = (
        <Input
          {...common}
          dir="ltr"
          inputMode={field.type === "integer" ? "numeric" : "decimal"}
          className="text-start"
          value={str}
          onChange={(e) => onChange(toFaDigits(e.target.value))}
        />
      );
      break;
    case "phone":
      control = (
        <Input
          {...common}
          type="tel"
          dir="ltr"
          className="text-start"
          value={str}
          onChange={(e) => onChange(toFaDigits(e.target.value))}
        />
      );
      break;
    case "boolean":
      control = (
        <div className="flex items-center gap-2">
          <Switch id={id} checked={value === true} onCheckedChange={onChange} aria-describedby={invalid ? errId : undefined} />
          <span className="text-small text-fg-muted">{value === true ? "بله" : "خیر"}</span>
        </div>
      );
      break;
    case "choice":
      control = (
        <Select {...common} value={str} onChange={(e) => onChange(e.target.value)}>
          <option value="">انتخاب کنید…</option>
          {(field.choices ?? []).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
      );
      break;
    case "datetime":
      control = (
        <JalaliDateTimeInput
          id={id}
          value={str}
          onChange={onChange}
          timeZone={timeZone}
          invalid={invalid}
          describedBy={invalid ? errId : undefined}
        />
      );
      break;
    default:
      control = <Input {...common} value={str} onChange={(e) => onChange(e.target.value)} />;
  }

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>
        {field.label}
        {!field.required && <span className="font-normal text-fg-muted"> (اختیاری)</span>}
      </Label>
      {control}
      {error && (
        <p id={errId} role="alert" className="text-small text-danger-text">
          {error}
        </p>
      )}
    </div>
  );
}
