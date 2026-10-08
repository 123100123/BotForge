import { Check, CircleAlert, LoaderCircle, X } from "lucide-react";
import { fa } from "@/lib/format";
import type { PhaseEntry, PhaseState, ToolEntry } from "@/lib/agent-state";
import { cn } from "@/lib/utils";
import { phaseLabel, toolLabel } from "./labels";

/**
 * The only animated element of the Changes page: the step that is running spins (reduced motion removes
 * the animation globally and leaves the icon).
 */
function StateIcon({ state }: { state: PhaseState }) {
  if (state === "running") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-brand-soft text-brand-text" role="img" aria-label="در حال انجام">
        <LoaderCircle strokeWidth={1.75} className="size-3.5 animate-spin" />
      </span>
    );
  }
  if (state === "done") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-success text-on-brand" role="img" aria-label="انجام شد">
        <Check strokeWidth={2} className="size-3.5" />
      </span>
    );
  }
  return (
    <span className="flex size-5 items-center justify-center rounded-full bg-danger text-on-brand" role="img" aria-label="ناموفق">
      <X strokeWidth={2} className="size-3.5" />
    </span>
  );
}

function ToolRow({ tool }: { tool: ToolEntry }) {
  return (
    <li className="flex flex-col gap-0.5 text-small">
      <div className="flex items-start gap-2">
        <span className="mt-2.5 size-1.5 shrink-0 rounded-[2px] bg-fg-muted/50" aria-hidden />
        <div className="min-w-0">
          <div className="font-medium text-fg">{toolLabel(tool.name)}</div>
          <div className="whitespace-pre-line text-fg-secondary">{tool.summary}</div>
          <span dir="ltr" className="mt-0.5 inline-block font-mono text-caption text-fg-muted">
            {tool.name}
          </span>
        </div>
      </div>
      {tool.result ? (
        <div className={cn("ms-3.5 flex items-start gap-1.5 text-caption", tool.result.ok ? "text-success-text" : "text-danger-text")}>
          {tool.result.ok ? (
            <Check strokeWidth={1.75} aria-label="موفق" className="mt-1 size-3.5 shrink-0" />
          ) : (
            <CircleAlert strokeWidth={1.75} aria-label="ناموفق" className="mt-1 size-3.5 shrink-0" />
          )}
          <span className="whitespace-pre-line">{tool.result.summary}</span>
        </div>
      ) : (
        <div className="ms-3.5 text-caption text-fg-muted">در حال اجرا…</div>
      )}
    </li>
  );
}

function PhaseRow({ entry, last, technical }: { entry: PhaseEntry; last: boolean; technical: boolean }) {
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!last && <span className="absolute start-[9.5px] top-6 bottom-0 w-px bg-border-strong" aria-hidden />}
      <div className="z-10 shrink-0">
        <StateIcon state={entry.state} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 text-body font-medium">
          <span>{phaseLabel(entry.phase)}</span>
          {entry.attempt > 1 && <span className="text-caption font-normal text-fg-muted">(بار {fa(entry.attempt)})</span>}
        </div>
        {entry.summary && <p className="text-small text-fg-secondary">{entry.summary}</p>}
        {technical && entry.tools.length > 0 && (
          <ul className="mt-2 flex flex-col gap-2.5 rounded-sm bg-surface-sunken p-3">
            {entry.tools.map((tool) => (
              <ToolRow key={tool.id} tool={tool} />
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

interface ActivityTimelineProps {
  phases: PhaseEntry[];
  /**
   * "steps": the stages in the owner's words (live progress). "technical": the same stages with the
   * assistant's tool steps and their raw names (the «جزئیات فنی» disclosure). Tokens and cost never show.
   */
  variant?: "steps" | "technical";
  label?: string;
}

/** Phases as a vertical checklist; in the technical variant tool calls are nested under their phase. */
export function ActivityTimeline({ phases, variant = "steps", label = "پیشرفت کار دستیار" }: ActivityTimelineProps) {
  if (phases.length === 0) {
    return <p className="text-small text-fg-muted">هنوز فعالیتی ثبت نشده است.</p>;
  }
  return (
    <ol aria-label={label} className="flex flex-col">
      {phases.map((entry, i) => (
        <PhaseRow key={entry.key} entry={entry} last={i === phases.length - 1} technical={variant === "technical"} />
      ))}
    </ol>
  );
}
