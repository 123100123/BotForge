"use client";

import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTheme, type ThemePreference } from "@/lib/theme";
import { cn } from "@/lib/utils";

const OPTIONS: { value: ThemePreference; label: string; icon: typeof SunIcon }[] = [
  { value: "light", label: "روشن", icon: SunIcon },
  { value: "dark", label: "تیره", icon: MoonIcon },
  { value: "system", label: "مطابق سیستم", icon: MonitorIcon },
];

/** The theme preference as a visible radio group (settings page, mobile «بیشتر» sheet). */
export function ThemeChoice({ className, label = "پوسته" }: { className?: string; label?: string }) {
  const { preference, setPreference } = useTheme();
  return (
    <fieldset className={cn("flex flex-col gap-2", className)}>
      <legend className="mb-2 text-small font-medium text-fg">{label}</legend>
      <div className="grid grid-cols-3 gap-1 rounded-sm border border-border bg-surface-sunken p-1">
        {OPTIONS.map(({ value, label: optionLabel, icon: Icon }) => (
          <label
            key={value}
            className={cn(
              "flex min-h-11 cursor-pointer items-center justify-center gap-1.5 rounded-xs border border-transparent px-2 text-small font-medium text-fg-muted transition-colors duration-fast hover:text-fg has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand",
              preference === value && "border-border bg-surface text-fg",
            )}
          >
            <input
              type="radio"
              name="theme-preference"
              value={value}
              checked={preference === value}
              onChange={() => setPreference(value)}
              className="sr-only"
            />
            <Icon className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
            {optionLabel}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
