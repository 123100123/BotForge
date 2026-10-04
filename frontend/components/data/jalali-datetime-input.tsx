"use client";

import { useMemo, useState } from "react";
import { CalendarDays } from "lucide-react";
import { Calendar } from "react-multi-date-picker";
import TimePicker from "react-multi-date-picker/plugins/time_picker";
import persian from "react-date-object/calendars/persian";
import persian_fa from "react-date-object/locales/persian_fa";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import { isoToJalali, jalaliToIso } from "@/lib/jalali";
import { cn } from "@/lib/utils";

interface JalaliDateTimeInputProps {
  id: string;
  /** ISO 8601 string (any offset) or "" when unset. */
  value: string;
  /** ISO 8601 string with the Tehran offset, or "" when cleared. */
  onChange: (iso: string) => void;
  /** IANA zone the wall-clock time is entered and shown in (the collection's `timezone`). */
  timeZone?: string;
  invalid?: boolean;
  describedBy?: string;
}

/** Jalali date and time picker: a field that opens an inline calendar with a time selector. */
export function JalaliDateTimeInput({ id, value, onChange, timeZone, invalid, describedBy }: JalaliDateTimeInputProps) {
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => isoToJalali(value, timeZone), [value, timeZone]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <button
          type="button"
          id={id}
          aria-expanded={open}
          data-invalid={invalid || undefined}
          aria-describedby={describedBy}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-input bg-card px-3 text-start text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 data-[invalid=true]:border-destructive",
            !value && "text-muted-foreground",
          )}
        >
          <CalendarDays className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{value ? formatDateTime(value, timeZone) : "انتخاب تاریخ و ساعت"}</span>
        </button>
        {value && (
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange("")}>
            پاک کردن
          </Button>
        )}
      </div>
      {open && (
        <div className="self-start" dir="rtl">
          <Calendar
            calendar={persian}
            locale={persian_fa}
            value={selected}
            onChange={(d) => {
              if (d && !Array.isArray(d)) onChange(jalaliToIso(d, timeZone));
            }}
            plugins={[<TimePicker key="time" hideSeconds />]}
          />
        </div>
      )}
    </div>
  );
}
