import { CONTAINER } from "./nav";
import { RolesDemo } from "./roles-demo";

/** «یک ربات، سه نقش»: heading, then the one interactive panel. */
export function RolesSection() {
  return (
    <section id="roles" aria-labelledby="roles-title" className="scroll-mt-16 border-y border-border bg-surface py-14 lg:py-20">
      <div className={CONTAINER}>
        <div className="mb-8 flex max-w-2xl flex-col gap-2">
          <h2 id="roles-title" className="text-h1 text-fg">
            یک ربات، سه نقش
          </h2>
          <p className="text-body text-fg-secondary">مشتری، کارمند و مدیر در همان تلگرام هستند و هرکدام فقط چیزی را می‌بینند که به کارش مربوط است.</p>
        </div>
        <RolesDemo />
      </div>
    </section>
  );
}
