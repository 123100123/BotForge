import { Badge } from "@/components/ui/badge";
import { namesOf, COMING_SOON } from "@/components/capabilities/labels";
import { fa } from "@/lib/format";
import type { CapabilityOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_CHIPS = 3;

/** One capability in the Capability Center: status, description, feature chips and what it needs. Opens its detail panel. */
export function CapabilityCard({
  cap,
  byId,
  onOpen,
}: {
  cap: CapabilityOut;
  byId: Map<string, CapabilityOut>;
  onOpen: () => void;
}) {
  const soon = COMING_SOON.has(cap.id);
  const needs = [
    ...(cap.requires.length > 0 ? [namesOf(cap.requires, byId)] : []),
    ...(cap.requires_any.length > 0 ? [`یکی از ${namesOf(cap.requires_any, byId)}`] : []),
  ].join(" و ");

  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${cap.name}، ${soon ? "به‌زودی" : cap.enabled ? "فعال" : "غیرفعال"}`}
      className={cn(
        "flex h-full flex-col gap-3 rounded-xl border bg-card p-4 text-start shadow-xs transition-colors outline-none hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/40",
        cap.enabled && "border-success/40",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm leading-6 font-semibold">{cap.name}</span>
        {soon ? (
          <Badge variant="warning">به‌زودی</Badge>
        ) : (
          <span
            aria-hidden
            className={cn("shrink-0 text-xs whitespace-nowrap", cap.enabled ? "text-success" : "text-muted-foreground")}
          >
            {cap.enabled ? "● فعال" : "○ غیرفعال"}
          </span>
        )}
      </div>
      <p className="text-sm leading-7 text-muted-foreground">{cap.description}</p>
      {cap.features.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="ویژگی‌ها">
          {cap.features.slice(0, MAX_CHIPS).map((f) => (
            <li key={f}>
              <Badge variant="accent">{f}</Badge>
            </li>
          ))}
          {cap.features.length > MAX_CHIPS && (
            <li>
              <Badge variant="outline">+{fa(cap.features.length - MAX_CHIPS)}</Badge>
            </li>
          )}
        </ul>
      )}
      {needs && <p className="mt-auto text-xs leading-6 text-muted-foreground">نیاز دارد به {needs}</p>}
    </button>
  );
}
