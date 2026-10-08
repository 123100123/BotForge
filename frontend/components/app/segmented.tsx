"use client";

import { Radio, RadioGroup, Label } from "@heroui/react";
import { cn } from "@/lib/utils";
export interface SegmentedOption<T extends string> { value: T; label: string }
export function Segmented<T extends string>({ value, onChange, options, label, className }: {
  value: T; onChange: (value: T) => void; options: SegmentedOption<T>[]; label: string; className?: string;
}) {
  return <RadioGroup aria-label={label} value={value} onChange={(next) => onChange(next as T)} orientation="horizontal" className={cn("flex max-w-full flex-row flex-wrap gap-1 rounded-2xl border bg-surface-secondary/60 p-1", className)}>
    {options.map((option) => <Radio key={option.value} value={option.value} className={cn("rounded-xl", value === option.value && "bg-card shadow-sm")}>
      <Radio.Content className="rounded-xl px-3 py-2"><Radio.Control className="sr-only"><Radio.Indicator /></Radio.Control><Label className={cn("cursor-pointer text-xs font-semibold sm:text-sm", value === option.value ? "text-primary" : "text-muted-foreground")}>{option.label}</Label></Radio.Content>
    </Radio>)}
  </RadioGroup>;
}
