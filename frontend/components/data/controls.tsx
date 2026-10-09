"use client";

import { Label, ListBox, Select, Switch } from "@heroui/react";

export interface ChoiceOption { value: string; label: string }

/** A compact single-select built from HeroUI V3's React Aria collection parts. */
export function ChoiceSelect({ id, label, value, options, onChange, isDisabled, isInvalid, describedBy, placeholder = "انتخاب کنید…", className = "" }: {
  id: string;
  label: string;
  value: string;
  options: ChoiceOption[];
  onChange: (value: string) => void;
  isDisabled?: boolean;
  isInvalid?: boolean;
  describedBy?: string;
  placeholder?: string;
  className?: string;
}) {
  return (
    <Select aria-label={label} aria-describedby={describedBy} isInvalid={isInvalid} value={value || null} onChange={(key) => onChange(key === null ? "" : String(key))} isDisabled={isDisabled} placeholder={placeholder} className={className}>
      <Select.Trigger id={id} aria-describedby={describedBy} aria-invalid={isInvalid || undefined} className="min-w-0">
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox items={options}>
          {(option) => <ListBox.Item id={option.value} textValue={option.label}><Label>{option.label}</Label></ListBox.Item>}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

/** HeroUI V3 switch anatomy shared by settings within operations and analyst flows. */
export function ToggleField({ id, label, value, onChange, isDisabled, describedBy, isInvalid, className = "" }: {
  id: string;
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
  isDisabled?: boolean;
  describedBy?: string;
  isInvalid?: boolean;
  className?: string;
}) {
  return (
    <Switch id={id} aria-label={label} aria-describedby={describedBy} aria-invalid={isInvalid || undefined} isSelected={value} onChange={onChange} isDisabled={isDisabled} className={className}>
      <Switch.Content>
        <Switch.Control><Switch.Thumb /></Switch.Control>
        <Label>{label}</Label>
      </Switch.Content>
    </Switch>
  );
}
