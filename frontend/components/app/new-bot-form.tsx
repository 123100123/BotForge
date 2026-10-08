"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { sectionHref } from "@/lib/routes";

/**
 * Creates a business from a name and opens its Changes page, where the assistant builds it.
 * (Formerly the body of the new-bot dialog; Phase 4 turns /bots/new into the onboarding composer.)
 */
export function NewBotForm({ secondaryAction }: { secondaryAction?: ReactNode }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("نام کسب‌وکار را وارد کنید.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const bot = await api.createBot(trimmed);
      router.push(sectionHref(bot.id, "changes"));
    } catch (err) {
      setError(errorMessage(err));
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Label htmlFor="bot-name">نام کسب‌وکار</Label>
        <Input
          id="bot-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          autoComplete="off"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "bot-name-error" : "bot-name-hint"}
        />
        {error ? (
          <p id="bot-name-error" role="alert" className="text-caption text-danger-text">
            {error}
          </p>
        ) : (
          <p id="bot-name-hint" className="text-caption text-fg-muted">
            همان نامی که مشتری‌ها می‌شناسند؛ بعداً هم می‌توانید آن را عوض کنید.
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" loading={pending}>
          {pending ? "در حال ساخت…" : "ساخت کسب‌وکار"}
        </Button>
        {secondaryAction}
      </div>
    </form>
  );
}
