import type { ReactNode } from "react";
import { SimpleHeader } from "@/components/app/simple-header";
import { SKIP_LINK_CLASS } from "@/components/app/shell/skip-link";

/** /bots and /bots/new: outside any business, so a simple header instead of the Control Center shell. */
export default function HomeLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-page">
      <a href="#main" className={SKIP_LINK_CLASS}>
        پرش به محتوا
      </a>
      <SimpleHeader />
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:py-8">
        {children}
      </main>
    </div>
  );
}
