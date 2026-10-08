import Link from "next/link";
import { ArrowDownIcon } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { CTA_SIGNUP_LABEL } from "./data";
import { HeroComposition } from "./hero-composition";
import { CONTAINER } from "./nav";

/** Split hero: copy at the start edge, the product composition at the end edge. Stacks copy-first below 1024px. */
export function Hero() {
  return (
    <section aria-labelledby="hero-title" className={`${CONTAINER} grid items-start gap-10 pt-8 pb-14 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12 lg:pt-12 lg:pb-20`}>
      <div className="flex flex-col items-start gap-6 lg:pt-6">
        <h1 id="hero-title" className="text-display text-fg">
          کسب‌وکارتان را <br className="hidden lg:block" />
          از&nbsp;تلگرام اداره کنید.
        </h1>
        <p className="max-w-[34rem] text-h3 font-normal text-fg-secondary">
          بگویید کسب‌وکارتان چطور کار می‌کند. دستیار بات‌فورج ربات تلگرامی می‌سازد که سفارش، رزرو، رویداد و گزارش را برایتان می‌گرداند.
        </p>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link href="/signup" className={buttonVariants({ size: "lg" })}>
            {CTA_SIGNUP_LABEL}
          </Link>
          <a href="#roles" className="inline-flex items-center gap-1.5 rounded-xs text-body font-medium text-brand-text underline-offset-4 hover:underline">
            نمونهٔ واقعی را ببینید
            <ArrowDownIcon className="size-4" strokeWidth={1.75} aria-hidden />
          </a>
        </div>
      </div>
      <HeroComposition />
    </section>
  );
}
