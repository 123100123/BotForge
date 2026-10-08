"use client";

import Link from "next/link";
import { CircleCheckIcon, CircleIcon, ClockIcon } from "lucide-react";
import { isAvailable, namesOf } from "@/components/capabilities/labels";
import { StatusBadge } from "@/components/ui/status-badge";
import { Switch } from "@/components/ui/switch";
import type { CapabilityOut } from "@/lib/types";
import { cn } from "@/lib/utils";

/** State as icon + word (never color alone): فعال, خاموش, or به‌زودی (dashed, for capabilities that cannot be switched on yet). */
export function CapabilityState({ cap, className }: { cap: CapabilityOut; className?: string }) {
  if (!isAvailable(cap)) {
    return (
      <StatusBadge
        tone="neutral"
        icon={<ClockIcon strokeWidth={1.75} aria-hidden />}
        className={cn("border border-dashed border-border-strong bg-transparent text-fg-muted", className)}
      >
        به‌زودی
      </StatusBadge>
    );
  }
  return cap.enabled ? (
    <StatusBadge tone="success" icon={<CircleCheckIcon strokeWidth={1.75} aria-hidden />} className={className}>
      فعال
    </StatusBadge>
  ) : (
    <StatusBadge tone="neutral" icon={<CircleIcon strokeWidth={1.75} aria-hidden />} className={className}>
      خاموش
    </StatusBadge>
  );
}

/** «نیازمند: فهرست محصولات» for the dependencies of a capability, or null when it has none. */
export function dependencyHint(cap: CapabilityOut, byId: Map<string, CapabilityOut>): string | null {
  const parts: string[] = [];
  if (cap.requires.length > 0) parts.push(namesOf(cap.requires, byId));
  if (cap.requires_any.length > 0) parts.push(`یکی از ${namesOf(cap.requires_any, byId)}`);
  return parts.length > 0 ? `نیازمند: ${parts.join(" و ")}` : null;
}

/**
 * One capability as a ruled row: name, purpose, state, dependency hint and the switch. The main area is a link
 * (its own route; the list swaps to its detail pane instead when `onSelect` is given). The switch is a
 * sibling, not a child, and only asks to change the state: the consequence sheet decides.
 */
export function CapabilityRow({
  cap,
  byId,
  href,
  selected,
  onSelect,
  onToggleRequest,
}: {
  cap: CapabilityOut;
  byId: Map<string, CapabilityOut>;
  href: string;
  selected: boolean;
  /** Wide layout: show the detail beside the list instead of navigating. */
  onSelect?: () => void;
  onToggleRequest: () => void;
}) {
  const available = isAvailable(cap);
  const hint = dependencyHint(cap, byId);
  return (
    <li className={cn("flex items-stretch transition-colors duration-fast", selected ? "bg-brand-soft" : "hover:bg-surface-sunken")}>
      <Link
        href={href}
        aria-current={selected ? "true" : undefined}
        onClick={(e) => {
          if (!onSelect || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
          e.preventDefault();
          onSelect();
        }}
        className="flex min-w-0 flex-1 flex-col gap-1 px-4 py-3 -outline-offset-2"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 className={cn("text-h3", available ? "text-fg" : "text-fg-secondary")}>{cap.name}</h3>
          <CapabilityState cap={cap} />
        </div>
        <p className={cn("line-clamp-1 text-small", available ? "text-fg-secondary" : "text-fg-muted")}>{cap.description}</p>
        {hint && <p className="text-caption text-fg-muted">{hint}</p>}
      </Link>
      {available && (
        <div className="flex shrink-0 items-center pe-4 ps-1">
          <Switch
            checked={cap.enabled}
            onCheckedChange={onToggleRequest}
            aria-label={`فعال بودن ${cap.name}`}
            className="relative before:absolute before:-inset-x-2 before:-inset-y-3 before:content-['']"
          />
        </div>
      )}
    </li>
  );
}
