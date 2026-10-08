import Link from "next/link";
import { Logo } from "@/components/app/logo";
import { buttonVariants } from "@/components/ui/button";
import { CTA_SIGNUP_LABEL } from "./data";
import { CONTAINER, SECTION_LINKS } from "./nav";

/** Closing band on the brand-soft surface: one sentence and the same primary action as the hero. */
export function ClosingBand() {
  return (
    <section aria-labelledby="closing-title" className="border-y border-border bg-brand-soft py-14 lg:py-16">
      <div className={`${CONTAINER} flex flex-col items-start gap-6 md:flex-row md:items-center md:justify-between md:gap-10`}>
        <h2 id="closing-title" className="max-w-xl text-h1 text-fg">
          از یک توضیح ساده شروع کنید. بقیه‌اش را دستیار می‌سازد.
        </h2>
        <Link href="/signup" className={buttonVariants({ size: "lg" })}>
          {CTA_SIGNUP_LABEL}
        </Link>
      </div>
    </section>
  );
}

/** One row: mark, sign-in, anchors, and the Latin product name. */
export function LandingFooter() {
  return (
    <footer className="py-8">
      <div className={`${CONTAINER} flex flex-wrap items-center gap-x-8 gap-y-4`}>
        <Logo size={26} />
        <nav aria-label="پیوندها" className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <Link href="/login" className="rounded-xs text-small text-fg-secondary hover:text-fg">
            ورود
          </Link>
          {SECTION_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="rounded-xs text-small text-fg-secondary hover:text-fg">
              {link.label}
            </a>
          ))}
        </nav>
        <span dir="ltr" className="ms-auto text-small text-fg-muted">
          BotForge
        </span>
      </div>
    </footer>
  );
}
