"use client";

import Link from "next/link";
import { ArrowRightIcon, MessageSquareIcon, PowerIcon } from "lucide-react";
import { useBusiness } from "@/components/app/business-context";
import { useCapabilities } from "@/components/capabilities/capabilities-provider";
import { CapabilityConfig, hasConfigFields } from "@/components/capabilities/capability-config";
import { CapabilityState } from "@/components/capabilities/capability-row";
import { AUDIENCE_SEES, NAV_ITEM_OF_CAPABILITY, isAvailable, metricLabel } from "@/components/capabilities/labels";
import { Button, buttonVariants } from "@/components/ui/button";
import { sectionHref } from "@/lib/routes";
import type { CapabilityOut } from "@/lib/types";
import { cn } from "@/lib/utils";

export function capabilityHref(botId: string, capId: string): string {
  return `${sectionHref(botId, "capabilities")}/${encodeURIComponent(capId)}`;
}

function Section({ title, level, children }: { title: string; level: "h2" | "h3"; children: React.ReactNode }) {
  const Heading = level;
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-4">
      <Heading className="text-h3 text-fg">{title}</Heading>
      {children}
    </section>
  );
}

/** The one primary action of a capability: turn on, turn off, or configure with the assistant. Always opens the consequence sheet. */
export function CapabilityPrimaryAction({ cap, className }: { cap: CapabilityOut; className?: string }) {
  const { requestToggle } = useCapabilities();
  if (!isAvailable(cap)) return null;
  if (cap.enabled) {
    return (
      <Button variant="secondary" className={className} onClick={() => requestToggle(cap)}>
        <PowerIcon strokeWidth={1.75} aria-hidden />
        خاموش کردن
      </Button>
    );
  }
  return (
    <Button className={className} onClick={() => requestToggle(cap)}>
      {cap.needs_agent ? <MessageSquareIcon strokeWidth={1.75} aria-hidden /> : <PowerIcon strokeWidth={1.75} aria-hidden />}
      {cap.needs_agent ? "پیکربندی با دستیار" : "روشن کردن"}
    </Button>
  );
}

/** A capability named inside the detail: opens in the pane on wide screens (`onPick`), otherwise its own route. */
function CapabilityLink({ cap, onPick }: { cap: CapabilityOut; onPick?: (id: string) => void }) {
  const { bot } = useBusiness();
  return (
    <Link
      href={capabilityHref(bot.id, cap.id)}
      onClick={(e) => {
        if (!onPick || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        onPick(cap.id);
      }}
      className="rounded-xs text-brand-text underline-offset-4 hover:underline"
    >
      {cap.name}
    </Link>
  );
}

function DependencyRow({ cap, onPick }: { cap: CapabilityOut; onPick?: (id: string) => void }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <CapabilityLink cap={cap} onPick={onPick} />
      <CapabilityState cap={cap} />
    </li>
  );
}

/** What the capability needs, grouped: needs all of, needs one of, cannot run with, and who depends on it. */
function Dependencies({ cap, level, onPick }: { cap: CapabilityOut; level: "h2" | "h3"; onPick?: (id: string) => void }) {
  const { all, byId } = useCapabilities();
  const pick = (ids: string[]) => ids.flatMap((id) => byId.get(id) ?? []);
  const needs = pick(cap.requires);
  const needsOne = pick(cap.requires_any);
  const conflicts = pick(cap.conflicts);
  const dependents = all.filter((c) => c.requires.includes(cap.id) || c.requires_any.includes(cap.id));
  const groups: { label: string; items: CapabilityOut[] }[] = [
    { label: "برای کار کردن به این‌ها نیاز دارد", items: needs },
    { label: "حداقل یکی از این‌ها لازم است", items: needsOne },
    { label: "با این‌ها هم‌زمان کار نمی‌کند", items: conflicts },
    { label: "این قابلیت‌ها به آن وابسته‌اند", items: dependents },
  ].filter((g) => g.items.length > 0);

  return (
    <Section title="وابستگی‌ها" level={level}>
      {groups.length === 0 ? (
        <p className="text-small text-fg-muted">این قابلیت مستقل است: به قابلیت دیگری نیاز ندارد و قابلیتی هم به آن وابسته نیست.</p>
      ) : (
        groups.map((g) => (
          <div key={g.label} className="flex flex-col gap-1">
            <p className="text-small text-fg-secondary">{g.label}</p>
            <ul className="flex flex-col gap-1 text-small">
              {g.items.map((c) => (
                <DependencyRow key={c.id} cap={c} onPick={onPick} />
              ))}
            </ul>
          </div>
        ))
      )}
      {cap.enabled && dependents.some((c) => c.enabled) && (
        <p className="text-small text-fg-muted">با خاموش کردن «{cap.name}»، قابلیت‌های روشنِ وابسته هم خاموش می‌شوند؛ پیش از تأیید همه را می‌بینید.</p>
      )}
    </Section>
  );
}

function Metrics({ cap, level }: { cap: CapabilityOut; level: "h2" | "h3" }) {
  const { bot, nav } = useBusiness();
  const navId = NAV_ITEM_OF_CAPABILITY[cap.id];
  const page = navId ? nav.flatMap((g) => [...g.items, ...g.overflow]).find((i) => i.id === navId) : undefined;
  if (cap.metrics.length === 0 && !page) return null;
  return (
    <Section title="شاخص‌ها" level={level}>
      {cap.metrics.length > 0 ? (
        <>
          <p className="text-small text-fg-secondary">این قابلیت در گزارش‌ها این شاخص‌ها را اضافه می‌کند:</p>
          <ul className="flex list-disc flex-col gap-1 ps-5 text-small marker:text-fg-muted">
            {cap.metrics.map((m) => (
              <li key={m}>{metricLabel(m)}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-small text-fg-muted">این قابلیت شاخص جداگانه‌ای به گزارش‌ها اضافه نمی‌کند.</p>
      )}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        {cap.metrics.length > 0 && (
          <Link href={sectionHref(bot.id, "reports")} className={cn(buttonVariants({ variant: "link" }), "text-small")}>
            دیدن گزارش
            <ArrowRightIcon className="rtl:-scale-x-100" strokeWidth={1.75} aria-hidden />
          </Link>
        )}
        {page && (
          <Link href={page.href} className={cn(buttonVariants({ variant: "link" }), "text-small")}>
            رفتن به {page.label}
            <ArrowRightIcon className="rtl:-scale-x-100" strokeWidth={1.75} aria-hidden />
          </Link>
        )}
      </div>
    </Section>
  );
}

/** Sections of one capability: what users see, dependencies, settings, metrics. `level` is the heading level of the sections. */
export function CapabilityDetailBody({
  cap,
  level,
  onPick,
}: {
  cap: CapabilityOut;
  level: "h2" | "h3";
  onPick?: (id: string) => void;
}) {
  const { patch } = useCapabilities();
  const { bot } = useBusiness();
  const soon = !isAvailable(cap);
  const lead = cap.audience !== null ? (AUDIENCE_SEES[cap.audience] ?? "امکانات این قابلیت") : "امکانات این قابلیت";

  return (
    <div className="flex flex-col gap-4">
      {cap.features.length > 0 && (
        <Section title="کاربران چه می‌بینند" level={level}>
          <p className="text-small text-fg-secondary">{lead}:</p>
          <ul className="flex list-disc flex-col gap-1 ps-5 text-small marker:text-fg-muted">
            {cap.features.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </Section>
      )}

      <Dependencies cap={cap} level={level} onPick={onPick} />

      <Section title="تنظیمات" level={level}>
        {soon ? (
          <p className="text-small text-fg-muted">این قابلیت به‌زودی اضافه می‌شود و هنوز تنظیمی ندارد.</p>
        ) : hasConfigFields(cap) ? (
          cap.enabled ? (
            <CapabilityConfig key={cap.id} botId={bot.id} cap={cap} onSaved={patch} />
          ) : (
            <p className="text-small text-fg-muted">پس از روشن کردن قابلیت می‌توانید آن را تنظیم کنید.</p>
          )
        ) : (
          <p className="text-small text-fg-muted">
            این قابلیت تنظیم جداگانه ندارد. برای تغییر رفتار آن، از دستیار بخواهید؛ تغییر را پیش از اعمال می‌بینید و تأیید می‌کنید.
          </p>
        )}
      </Section>

      <Metrics cap={cap} level={level} />
    </div>
  );
}

/** Detail pane beside the list (≥1280px): title, state, primary action, purpose, then the sections. */
export function CapabilityDetailPane({ cap, onPick }: { cap: CapabilityOut; onPick?: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 className="text-h2 text-fg">{cap.name}</h2>
          <CapabilityState cap={cap} />
        </div>
        <p className="text-body text-fg-secondary">{cap.description}</p>
        <CapabilityPrimaryAction cap={cap} className="self-start" />
      </div>
      <CapabilityDetailBody cap={cap} level="h3" onPick={onPick} />
    </div>
  );
}
