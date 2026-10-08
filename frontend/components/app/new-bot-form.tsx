"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { BUSINESS_EXAMPLES } from "@/components/changes/examples";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { sectionHref } from "@/lib/routes";

const MIN_DESCRIPTION = 10;

/**
 * Onboarding form: the business name and a description of what it does. Submitting creates the business,
 * starts the assistant's first run with that description and opens the Changes page, where the bot's
 * run provider picks the run up. If the run could not be started the business already exists, so a retry
 * only repeats that step instead of creating a second business.
 */
export function NewBotForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<{ name?: string; description?: string; form?: string }>({});
  const [pending, setPending] = useState(false);
  const [createdBotId, setCreatedBotId] = useState<string | null>(null);

  function pick(example: (typeof BUSINESS_EXAMPLES)[number]) {
    setDescription(example.description);
    if (name.trim() === "") setName(example.name);
    setErrors({});
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();
    const next: typeof errors = {};
    if (!trimmedName) next.name = "نام کسب‌وکار را وارد کنید.";
    if (trimmedDescription.length < MIN_DESCRIPTION) {
      next.description = "کسب‌وکارتان را کمی بیشتر توضیح دهید تا دستیار بتواند ربات را بسازد.";
    }
    setErrors(next);
    if (next.name || next.description) return;

    setPending(true);
    let created: string | null = createdBotId;
    try {
      let botId = createdBotId;
      if (!botId) {
        botId = (await api.createBot(trimmedName)).id;
        setCreatedBotId(botId);
      }
      created = botId;
      await api.createRun(botId, trimmedDescription);
      router.push(sectionHref(botId, "changes"));
    } catch (err) {
      setErrors({
        form: created
          ? `کسب‌وکار ساخته شد، اما شروع کار دستیار انجام نشد. ${errorMessage(err)} دوباره «ساخت ربات» را بزنید.`
          : errorMessage(err),
      });
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Label htmlFor="bot-name">نام کسب‌وکار</Label>
        <Input
          id="bot-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          autoComplete="off"
          disabled={pending || createdBotId !== null}
          aria-invalid={Boolean(errors.name)}
          aria-describedby={errors.name ? "bot-name-error" : "bot-name-hint"}
          placeholder="مثلاً آموزشگاه نوآوران"
        />
        {errors.name ? (
          <p id="bot-name-error" role="alert" className="text-caption text-danger-text">
            {errors.name}
          </p>
        ) : (
          <p id="bot-name-hint" className="text-caption text-fg-muted">
            همان نامی که مشتری‌ها می‌شناسند؛ بعداً هم می‌توانید آن را عوض کنید.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="bot-description" className="text-h3">
          کسب‌وکارتان چه می‌کند و ربات چه کاری انجام دهد؟
        </Label>
        <Textarea
          id="bot-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={8}
          disabled={pending}
          aria-invalid={Boolean(errors.description)}
          aria-describedby={errors.description ? "bot-description-error" : "bot-description-hint"}
          placeholder="به زبان ساده بنویسید؛ مثلاً: من یک آموزشگاه دارم و می‌خواهم مشتری‌ها در ربات تلگرام کارگاه‌ها را ببینند و ثبت‌نام کنند…"
          className="min-h-48 resize-y"
        />
        {errors.description ? (
          <p id="bot-description-error" role="alert" className="text-caption text-danger-text">
            {errors.description}
          </p>
        ) : (
          <p id="bot-description-hint" className="text-caption text-fg-muted">
            بنویسید مشتری‌ها چه چیزی می‌خواهند و شما چه چیزی را می‌خواهید ببینید یا تأیید کنید. جزئیات کم باشد هم اشکالی ندارد؛
            دستیار می‌پرسد.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-small font-medium text-fg">نمونه‌ها</span>
        <div className="flex flex-wrap gap-2" role="group" aria-label="نمونهٔ کسب‌وکار">
          {BUSINESS_EXAMPLES.map((example) => (
            <Button
              key={example.id}
              type="button"
              variant="secondary"
              size="sm"
              disabled={pending}
              onClick={() => pick(example)}
            >
              {example.label}
            </Button>
          ))}
        </div>
        <p className="text-caption text-fg-muted">یکی را بزنید تا توضیح آن در کادر بالا بیاید؛ بعد می‌توانید آن را تغییر دهید.</p>
      </div>

      {errors.form && (
        <p role="alert" className="rounded-sm bg-danger-soft p-3 text-small text-danger-text">
          {errors.form}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="lg" loading={pending}>
          {pending ? "در حال شروع…" : "ساخت ربات"}
        </Button>
        <Button asChild variant="ghost" size="lg">
          <Link href="/bots?all=1">انصراف</Link>
        </Button>
      </div>
    </form>
  );
}
