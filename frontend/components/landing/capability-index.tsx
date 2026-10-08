import { StatusBadge } from "@/components/ui/status-badge";
import { fa } from "@/lib/format";
import { CAPABILITY_GROUPS } from "./data";
import { CONTAINER } from "./nav";

const TOTAL = CAPABILITY_GROUPS.reduce((n, g) => n + g.items.length, 0);

/** Dense two-column index of the registry (definition lists, ruled rows), not an icon-card grid. */
export function CapabilityIndex() {
  return (
    <section id="capabilities" aria-labelledby="cap-title" className="scroll-mt-16 border-y border-border bg-surface py-14 lg:py-20">
      <div className={CONTAINER}>
        <div className="flex max-w-2xl flex-col gap-2">
          <h2 id="cap-title" className="text-h1 text-fg">
            یک ربات. تمام کسب‌وکار شما.
          </h2>
          <p className="text-body text-fg-secondary">
            {fa(TOTAL)} قابلیت در {fa(CAPABILITY_GROUPS.length)} دسته. هر ربات فقط قابلیت‌هایی را دارد که برایش روشن کرده‌اید.
          </p>
        </div>
        <div className="mt-10 gap-x-14 lg:columns-2">
          {CAPABILITY_GROUPS.map((group) => (
            <div key={group.id} className="mb-10 break-inside-avoid">
              <h3 className="border-b border-border-strong pb-2 text-h3 text-fg">{group.title}</h3>
              <dl className="divide-y divide-border">
                {group.items.map((item) => (
                  <div key={item.name} className="grid gap-x-4 py-2.5 sm:grid-cols-[11.5rem_minmax(0,1fr)]">
                    <dt className={`flex flex-wrap items-center gap-2 text-body font-medium ${item.soon ? "text-fg-muted" : "text-fg"}`}>
                      {item.name}
                      {item.soon && <StatusBadge tone="neutral">به‌زودی</StatusBadge>}
                    </dt>
                    <dd className={`text-body ${item.soon ? "text-fg-muted" : "text-fg-secondary"}`}>{item.purpose}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
