import type { ReactNode } from "react";
import { ChangeStateBadge } from "@/components/changes/change-state";
import { ConfigDiff } from "@/components/changes/config-diff";
import { QuestionCard } from "@/components/changes/question-card";
import { RequirementsList } from "@/components/changes/requirements-list";
import { TestSummary } from "@/components/changes/test-summary";
import { fa } from "@/lib/format";
import { cn } from "@/lib/utils";
import { HOW_CHANGE_REQUEST, HOW_DESCRIPTION, HOW_DIFF, HOW_QUESTIONS, HOW_REQUIREMENTS, HOW_TESTS } from "./data";
import { CONTAINER } from "./nav";

/** A framed specimen of a real component; the caption row names where it lives in the product. */
function Specimen({ caption, badge, children, className }: { caption: string; badge?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-md border border-border bg-surface", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-2.5">
        <span className="text-small font-medium text-fg-secondary">{caption}</span>
        {badge}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

interface Step {
  title: string;
  text: string;
  visual: ReactNode;
}

const STEPS: Step[] = [
  {
    title: "توضیح می‌دهید",
    text: "کسب‌وکارتان را با همان کلمات خودتان بنویسید. لازم نیست چیزی از ربات یا برنامه‌نویسی بدانید.",
    visual: (
      <figure className="rounded-md border border-border-strong bg-surface-raised p-5">
        <figcaption className="mb-2 text-caption text-fg-muted">توضیح شما</figcaption>
        <blockquote className="text-body text-fg">{HOW_DESCRIPTION}</blockquote>
      </figure>
    ),
  },
  {
    title: "دستیار برداشتش را نشان می‌دهد",
    text: "پیش از ساختن، می‌بینید چه فهمیده و چه فرضی کرده است. اگر چیزی را نمی‌داند، همین‌جا می‌پرسد.",
    visual: (
      <div className="flex flex-col gap-4">
        <Specimen caption="برداشت دستیار از کسب‌وکار شما">
          <RequirementsList requirements={HOW_REQUIREMENTS} />
        </Specimen>
        <QuestionCard questions={HOW_QUESTIONS} answer={null} />
      </div>
    ),
  },
  {
    title: "تأیید می‌کنید و ربات فعال می‌شود",
    text: "ربات پیش از فعال شدن با آزمون‌های خودکار سنجیده می‌شود. شما نتیجه را می‌بینید و تأیید می‌کنید.",
    visual: (
      <Specimen caption={`نسخهٔ ${fa(1)}`} badge={<ChangeStateBadge state="active" />}>
        <TestSummary {...HOW_TESTS} />
      </Specimen>
    ),
  },
  {
    title: "بعداً با یک جمله تغییرش می‌دهید",
    text: "چیزی را عوض کنید و فقط تفاوتش را ببینید. هر تغییر یک نسخهٔ تازه است و می‌توانید به قبلی برگردید.",
    visual: (
      <Specimen caption="پیشنهاد تغییر" badge={<ChangeStateBadge state="ready" />}>
        <div className="flex flex-col gap-4">
          <p className="w-fit max-w-full rounded-md rounded-ee-xs bg-brand-soft px-3 py-2 text-body text-fg">{HOW_CHANGE_REQUEST}</p>
          <ConfigDiff changes={HOW_DIFF} />
        </div>
      </Specimen>
    ),
  },
];

/** A true four-step vertical sequence; each step shows the real component the owner meets at that point. */
export function HowItWorks() {
  return (
    <section id="how" aria-labelledby="how-title" className="scroll-mt-16 py-14 lg:py-20">
      <div className={CONTAINER}>
        <h2 id="how-title" className="text-h1 text-fg">
          از یک توضیح تا ربات آماده
        </h2>
        <ol className="mt-10 flex flex-col gap-12 lg:gap-14">
          {STEPS.map((step, i) => (
            <li key={step.title} className="relative grid gap-5 ps-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12">
              <span
                aria-hidden
                className="absolute start-0 top-0 grid size-8 place-items-center rounded-full bg-brand text-small font-bold text-on-brand"
              >
                {fa(i + 1)}
              </span>
              {i < STEPS.length - 1 && <span aria-hidden className="absolute start-4 top-10 -bottom-12 w-px bg-border-strong lg:-bottom-14" />}
              <div className="flex flex-col gap-2 lg:pt-0.5">
                <h3 className="text-h2 text-fg">{step.title}</h3>
                <p className="max-w-[28rem] text-body text-fg-secondary">{step.text}</p>
              </div>
              <div className="min-w-0">{step.visual}</div>
            </li>
          ))}
        </ol>
        <p className="mt-12 border-s-4 border-brand ps-4 text-h2 text-fg">هیچ تغییری بدون تأیید شما فعال نمی‌شود.</p>
      </div>
    </section>
  );
}
