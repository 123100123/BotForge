"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface ChangeComposerProps {
  /** "first" is the fuller composer of the first build; "change" the compact one above the timeline. */
  variant?: "change" | "first";
  label: string;
  placeholder: string;
  submitLabel: string;
  /** Short examples the owner can drop into the box. */
  examples?: { label: string; text: string }[];
  /** When set the composer is disabled and this explains why. */
  disabledReason?: string | null;
  /** A request is in flight. */
  busy?: boolean;
  /** Helper line under the box. */
  hint?: string;
  onSubmit: (text: string) => void | Promise<void>;
  className?: string;
}

/** A sentence in, a change proposal out. Local draft state only: no context, no fetching. */
export function ChangeComposer({
  variant = "change",
  label,
  placeholder,
  submitLabel,
  examples = [],
  disabledReason,
  busy = false,
  hint,
  onSubmit,
  className,
}: ChangeComposerProps) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const first = variant === "first";

  async function submit() {
    const text = draft.trim();
    if (!text || busy) return;
    await onSubmit(text);
    setDraft("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  }

  // While a proposal is open the composer is only an explanation: no dead textarea.
  if (disabledReason) {
    return (
      <div className={cn("flex flex-col gap-2", className)}>
        <p className="text-small font-medium text-fg">{label}</p>
        <p role="status" className="flex items-start gap-2 rounded-sm bg-info-soft p-3 text-small text-info-text">
          <Info strokeWidth={1.75} aria-hidden className="mt-1 size-4 shrink-0" />
          {disabledReason}
        </p>
      </div>
    );
  }

  return (
    <form
      className={cn("flex flex-col gap-3", className)}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <Label htmlFor={id} className={first ? "text-h3" : undefined}>
        {label}
      </Label>
      <Textarea
        id={id}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={busy}
        rows={first ? 6 : 3}
        placeholder={placeholder}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={cn("resize-y", first && "min-h-40")}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-caption text-fg-muted">
          {hint}
        </p>
      )}
      {examples.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-caption text-fg-muted">نمونه‌ها (برای پر کردن کادر بزنید)</span>
          <div className="flex flex-wrap gap-2">
            {examples.map((example) => (
              <Button
                key={example.label}
                type="button"
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() => setDraft(example.text)}
                className="h-auto max-w-full py-1 text-start whitespace-normal"
              >
                {example.label}
              </Button>
            ))}
          </div>
        </div>
      )}
      <div>
        <Button type="submit" size={first ? "lg" : "md"} loading={busy} disabled={draft.trim() === ""}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
