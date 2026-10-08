"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ChoiceSelect, ToggleField } from "./controls";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { ApiError, ERROR_CODES, errorMessage } from "@/lib/errors";
import { toFaDigits } from "@/lib/format";
import type { DataCollection, DataRecord, FieldDef } from "@/lib/types";
import { ErrorNote } from "@/components/app/state-blocks";
import { initialValues, splitFieldErrors, toPayload, type FormValue, type FormValues } from "./field-utils";
import { JalaliDateTimeInput } from "./jalali-datetime-input";

interface RecordFormProps {
  botId: string;
  collection: DataCollection;
  /** The record being edited, or null to create one. */
  record: DataRecord | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}

export function RecordForm({ botId, collection, record, open, onOpenChange, onSaved }: RecordFormProps) {
  const [saving, setSaving] = useState(false);
  // The dialog content is unmounted when closed, so state starts fresh for every open.
  return (
      <Modal.Backdrop isOpen={open} onOpenChange={(next) => !saving && onOpenChange(next)} isDismissable={!saving} isKeyboardDismissDisabled={saving}>
        <Modal.Container size="lg" scroll="inside" className="max-h-[90dvh]">
          <Modal.Dialog className="max-h-[90dvh] overflow-y-auto">
            <RecordFormBody botId={botId} collection={collection} record={record} saving={saving} setSaving={setSaving} onClose={() => onOpenChange(false)} onSaved={onSaved} />
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
  );
}

function RecordFormBody({
  botId,
  collection,
  record,
  onClose,
  onSaved,
  saving,
  setSaving,
}: {
  botId: string;
  collection: DataCollection;
  record: DataRecord | null;
  onClose: () => void;
  onSaved: () => void;
  saving: boolean;
  setSaving: (saving: boolean) => void;
}) {
  const fields = collection.fields;
  const [values, setValues] = useState<FormValues>(() => initialValues(fields, record?.data));
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [generalErrors, setGeneralErrors] = useState<string[]>([]);

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
    } finally {
      setSaving(false);
    }
  }

  const title = record ? `ویرایش ${collection.label}` : `افزودن ${collection.label}`;

  return (
    <form onSubmit={submit} noValidate className="grid gap-4">
      <Modal.Header>
        <Modal.Heading>{title}</Modal.Heading>
        <p className="text-sm leading-7 text-muted-foreground">
          {record ? "تغییرات بلافاصله در ربات اعمال می‌شود." : "پس از ذخیره، این مورد بلافاصله در ربات نمایش داده می‌شود."}
        </p>
      </Modal.Header>

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
            <ErrorNote key={i}>{m}</ErrorNote>
          ))}
        </div>
      )}

      <Modal.Footer className="flex flex-wrap gap-2">
        <Button type="submit" isDisabled={saving} isPending={saving}>
          {saving ? "در حال ذخیره…" : "ذخیره"}
        </Button>
        <Button type="button" variant="outline" onPress={onClose} isDisabled={saving}>
          انصراف
        </Button>
      </Modal.Footer>
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
          <ToggleField id={id} label={field.label} describedBy={invalid ? errId : undefined} isInvalid={invalid} value={value === true} onChange={onChange} />
          <span className="text-sm text-muted-foreground">{value === true ? "بله" : "خیر"}</span>
        </div>
      );
      break;
    case "choice":
      control = (
        <ChoiceSelect id={id} label={field.label} describedBy={invalid ? errId : undefined} isInvalid={invalid} value={str} onChange={onChange} options={(field.choices ?? []).map((c) => ({ value: c, label: c }))} />
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
        {!field.required && <span className="font-normal text-muted-foreground"> (اختیاری)</span>}
      </Label>
      {control}
      {error && (
        <p id={errId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
