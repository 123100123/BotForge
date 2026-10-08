"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

const choices = [
  { key: "light", label: "حالت روشن", icon: Sun },
  { key: "dark", label: "حالت تیره", icon: Moon },
  { key: "system", label: "حالت دستگاه", icon: Monitor },
] as const;

const subscribe = () => () => {};

export function ThemeToggle({ className = "" }: { className?: string }) {
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const { theme, setTheme } = useTheme();

  if (!mounted) {
    return <div aria-hidden="true" className={`h-9 w-[108px] rounded-xl bg-secondary ${className}`} />;
  }

  return (
    <div role="group" aria-label="نمایش سایت" className={`inline-flex items-center gap-0.5 rounded-xl border border-border bg-surface-secondary p-0.5 ${className}`}>
      {choices.map(({ key, label, icon: Icon }) => (
        <Button
          key={key}
          aria-label={label}
          aria-pressed={theme === key}
          isIconOnly
          size="sm"
          variant={theme === key ? "secondary" : "ghost"}
          onPress={() => setTheme(key)}
          className="min-w-8 rounded-[10px]"
        >
          <Icon aria-hidden="true" className="size-4" />
        </Button>
      ))}
    </div>
  );
}
