"use client";

import { CircleCheck, CircleX } from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Requirement, Scenario, ScenarioResult, TranscriptEntry } from "@/lib/types";

const ACTOR_NAMES: Record<string, string> = { ali: "علی", sara: "سارا", reza: "رضا", owner: "مدیر" };

function actorName(id: string) {
  return ACTOR_NAMES[id] ?? id;
}

interface ScenarioDetailProps {
  scenario: Scenario;
  result: ScenarioResult | undefined;
  requirements: Requirement[];
}

/** One scenario: what it checks, the steps with their outcome, and the conversation it played. A well, not a card. */
export function ScenarioDetail({ scenario, result, requirements }: ScenarioDetailProps) {
  const linked = scenario.requirement_ids
    .map((id) => requirements.find((r) => r.id === id) ?? null)
    .filter((r): r is Requirement => r !== null);

  return (
    <div className="flex flex-col gap-4 rounded-md bg-surface-sunken p-4">
      <div className="flex flex-col gap-2">
        {result ? (
          <StatusBadge
            tone={result.passed ? "success" : "danger"}
            icon={result.passed ? <CircleCheck strokeWidth={1.75} aria-hidden /> : <CircleX strokeWidth={1.75} aria-hidden />}
          >
            {result.passed ? "موفق" : "ناموفق"}
          </StatusBadge>
        ) : (
          <StatusBadge tone="neutral" marker>
            اجرا نشده
          </StatusBadge>
        )}
        <h5 className="text-body font-semibold text-fg">{scenario.title}</h5>
        {scenario.capacity_override !== null && (
          <p className="text-caption text-fg-muted">
            این آزمون با ظرفیت آزمایشی {fa(scenario.capacity_override)} نفر اجرا می‌شود تا کوتاه بماند.
          </p>
        )}
      </div>

      {linked.length > 0 && (
        <section aria-label="خواستهٔ مرتبط" className="flex flex-col gap-1.5">
          <h5 className="text-small font-semibold text-fg">برای کدام خواسته؟</h5>
          <ul className="flex flex-col gap-1">
            {linked.map((r) => (
              <li key={r.id} className="text-small text-fg-secondary">
                {r.statement}
                <sup dir="ltr" className="ms-1 inline-block align-super font-mono text-caption leading-none text-fg-muted">
                  {r.id}
                </sup>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="مرحله‌ها" className="flex flex-col gap-2">
        <h5 className="text-small font-semibold text-fg">مرحله‌ها</h5>
        {result ? (
          <ol className="flex flex-col gap-1.5">
            {result.steps.map((s) => (
              <li
                key={s.index}
                aria-current={!s.passed ? "step" : undefined}
                className={cn("flex items-start gap-2 rounded-sm px-3 py-2 text-small", !s.passed && "bg-danger-soft")}
              >
                {s.passed ? (
                  <CircleCheck strokeWidth={1.75} aria-label="موفق" className="mt-1 size-4 shrink-0 text-success-text" />
                ) : (
                  <CircleX strokeWidth={1.75} aria-label="ناموفق" className="mt-1 size-4 shrink-0 text-danger-text" />
                )}
                <div className="min-w-0">
                  <div>
                    {s.index >= 0 && <span className="text-fg-muted">{fa(s.index + 1)}. </span>}
                    {s.narrative}
                  </div>
                  {s.message && <div className="font-medium text-danger-text">{s.message}</div>}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-small text-fg-muted">این آزمون هنوز اجرا نشده است.</p>
        )}
        {result && result.steps.length < scenario.steps.length && !result.passed && (
          <p className="text-caption text-fg-muted">
            بعد از مرحلهٔ ناموفق، {fa(scenario.steps.length - result.steps.length)} مرحلهٔ دیگر اجرا نشد.
          </p>
        )}
      </section>

      {result && result.transcript.length > 0 && <Transcript entries={result.transcript} />}
    </div>
  );
}

function Transcript({ entries }: { entries: TranscriptEntry[] }) {
  return (
    <section aria-label="گفتگوها" className="flex flex-col gap-2">
      <h5 className="text-small font-semibold text-fg">گفتگوی کاربران با ربات</h5>
      <ul className="flex flex-col gap-2 rounded-sm bg-surface p-3">
        {entries.map((e, i) => (
          <li key={i} className={cn("flex flex-col gap-1", e.direction === "in" ? "items-end" : "items-start")}>
            <span className="text-caption text-fg-muted">
              {e.direction === "in" ? `${actorName(e.actor)} می‌گوید` : `ربات به ${actorName(e.actor)}`}
            </span>
            <div
              dir="auto"
              className={cn(
                "max-w-[90%] rounded-md px-3 py-1.5 text-small whitespace-pre-wrap",
                e.direction === "in" ? "bg-brand-soft text-fg" : "border border-border bg-surface-sunken text-fg",
              )}
            >
              {e.text}
            </div>
            {e.buttons.length > 0 && (
              <div className="flex max-w-[90%] flex-wrap gap-1">
                {e.buttons.map((b, j) => (
                  <span key={j} className="rounded-xs bg-brand-soft px-2 py-0.5 text-caption text-brand-text">
                    {b}
                  </span>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
