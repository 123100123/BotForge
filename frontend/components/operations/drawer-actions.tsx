"use client";

import { Button } from "@/components/ui/button";
import type { RowAction } from "@/components/data/data-table";

/** The record's actions as buttons at the bottom of a drawer. A destructive action closes the drawer first, so its confirmation is not stacked on it. */
export function DrawerActions({ actions, onBeforeSelect }: { actions: RowAction[]; onBeforeSelect?: () => void }) {
  if (actions.length === 0) return null;
  return (
    <div className="mt-auto flex flex-row-reverse flex-wrap items-center justify-start gap-2 border-t border-border pt-4">
      {actions.map((a) => (
        <Button
          key={a.key}
          variant={a.danger ? "secondary" : "primary"}
          className={a.danger ? "text-danger-text hover:text-danger-text" : undefined}
          disabled={a.disabled}
          onClick={() => {
            if (a.danger) onBeforeSelect?.();
            a.onSelect();
          }}
        >
          {a.icon}
          {a.label}
        </Button>
      ))}
    </div>
  );
}
