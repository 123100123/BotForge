import { NewBotForm } from "@/components/app/new-bot-form";
import { PageHeader } from "@/components/ui/page-header";
import { fa } from "@/lib/format";

const NEXT_STEPS = [
  "دستیار آنچه فهمیده را نشان می‌دهد و اگر لازم باشد چند پرسش کوتاه می‌پرسد.",
  "ربات را می‌سازد و آن را با آزمون‌های خودکار می‌سنجد.",
  "شما نتیجه را می‌بینید و فقط با تأیید شما فعال می‌شود.",
];

/** /bots/new: describe the business; the assistant builds the first version on the Changes page. */
export default function NewBotPage() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <PageHeader
        title="کسب‌وکارتان را توضیح دهید"
        description="چند جمله دربارهٔ کسب‌وکارتان بنویسید؛ دستیار از روی آن ربات تلگرام شما را می‌سازد."
      />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <div className="rounded-md border border-border bg-surface p-5 sm:p-6">
          <NewBotForm />
        </div>
        <aside aria-labelledby="next-steps" className="flex flex-col gap-3 lg:pt-2">
          <h2 id="next-steps" className="text-h3 text-fg">
            بعد از این چه می‌شود؟
          </h2>
          <ol className="flex flex-col gap-3">
            {NEXT_STEPS.map((step, i) => (
              <li key={step} className="flex items-start gap-3 text-small text-fg-secondary">
                <span
                  aria-hidden
                  className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border-strong text-caption font-semibold text-fg-secondary"
                >
                  {fa(i + 1)}
                </span>
                <span className="pt-0.5">{step}</span>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </div>
  );
}
