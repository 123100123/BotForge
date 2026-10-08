import { Check, Lightbulb, Minus, Pencil, Plus, TriangleAlert } from "lucide-react";
import { REQUIREMENT_KIND_LABELS } from "@/components/agent/labels";
import { fa } from "@/lib/format";
import type { Requirement, Requirements, RequirementsDeltaView } from "@/lib/types";

/** Requirement code: a quiet fixed-width marker at the row end (a reference, never part of the sentence). */
function Code({ id }: { id: string }) {
  return (
    <span
      dir="ltr"
      title={`شمارهٔ نیاز ${id.replace(/\d+/, (d) => fa(d))}`}
      className="mt-1 w-7 shrink-0 text-center font-mono text-caption text-fg-muted"
    >
      {id}
    </span>
  );
}

function Row({ item, icon }: { item: Requirement; icon: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-body">
      <span aria-hidden className="mt-2 shrink-0 text-fg-muted [&_svg]:size-4">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        {item.statement}
        <span className="block text-caption text-fg-muted sm:hidden">{REQUIREMENT_KIND_LABELS[item.kind]}</span>
      </span>
      <span className="mt-1 w-20 shrink-0 text-caption text-fg-muted max-sm:hidden">{REQUIREMENT_KIND_LABELS[item.kind]}</span>
      <Code id={item.id} />
    </li>
  );
}

interface RequirementsListProps {
  requirements: Requirements;
  /** What this change altered in the understanding of the business (a modify run). */
  changes?: RequirementsDeltaView | null;
}

/**
 * What the assistant understood: confirmed requirements, then assumed ones on the warm surface, then what
 * cannot be built. Pure: props only.
 */
export function RequirementsList({ requirements, changes }: RequirementsListProps) {
  const confirmed = requirements.items.filter((r) => r.status === "confirmed");
  const assumed = requirements.items.filter((r) => r.status === "assumed");
  const added = changes?.added ?? [];
  const changed = changes?.changed ?? [];
  const removed = changes?.removed ?? [];
  const hasDelta = added.length + changed.length + removed.length > 0;

  return (
    <div className="flex flex-col gap-4">
      {requirements.business_summary && <p className="text-body text-fg-secondary">{requirements.business_summary}</p>}

      {confirmed.length > 0 && (
        <div className="flex flex-col gap-2">
          <h4 className="text-small font-semibold text-fg">
            مواردی که مطمئنم <span className="font-normal text-fg-muted">({fa(confirmed.length)})</span>
          </h4>
          <ul className="flex flex-col gap-2">
            {confirmed.map((item) => (
              <Row key={item.id} item={item} icon={<Check strokeWidth={1.75} />} />
            ))}
          </ul>
        </div>
      )}

      {assumed.length > 0 && (
        <div className="flex flex-col gap-2 rounded-md bg-warning-soft p-4">
          <h4 className="flex items-center gap-2 text-small font-semibold text-warning-text">
            <Lightbulb strokeWidth={1.75} className="size-4" aria-hidden />
            فرض‌هایی که خودم کرده‌ام <span className="font-normal">({fa(assumed.length)})</span>
          </h4>
          <p className="text-small text-fg-secondary">اگر درست نیست، همین‌جا یا در بخش «گفتگو» بنویسید تا اصلاح کنم.</p>
          <ul className="flex flex-col gap-2">
            {assumed.map((item) => (
              <Row key={item.id} item={item} icon={<Lightbulb strokeWidth={1.75} />} />
            ))}
          </ul>
        </div>
      )}

      {requirements.unsupported.length > 0 && (
        <div className="flex flex-col gap-2 rounded-md bg-danger-soft p-4">
          <h4 className="flex items-center gap-2 text-small font-semibold text-danger-text">
            <TriangleAlert strokeWidth={1.75} className="size-4" aria-hidden />
            آنچه فعلاً ساخته نمی‌شود <span className="font-normal">({fa(requirements.unsupported.length)})</span>
          </h4>
          <ul className="flex flex-col gap-3">
            {requirements.unsupported.map((u, i) => (
              <li key={i} className="text-body">
                <div className="font-medium">{u.statement}</div>
                <div className="text-small text-fg-secondary">دلیل: {u.reason}</div>
                {u.alternative && <div className="text-small text-fg-secondary">پیشنهاد دستیار: {u.alternative}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasDelta && (
        <div className="flex flex-col gap-2">
          <h4 className="text-small font-semibold text-fg">در این تغییر، برداشت دستیار از نیازها عوض شد</h4>
          <ul className="flex flex-col gap-2">
            {added.map((r) => (
              <li key={`a-${r.id}`} className="flex items-start gap-2.5 text-body">
                <Plus strokeWidth={1.75} aria-label="افزوده شد" className="mt-2 size-4 shrink-0 text-success-text" />
                <span className="min-w-0 flex-1">{r.statement}</span>
                <Code id={r.id} />
              </li>
            ))}
            {changed.map((r) => (
              <li key={`c-${r.id}`} className="flex items-start gap-2.5 text-body">
                <Pencil strokeWidth={1.75} aria-label="تغییر کرد" className="mt-2 size-4 shrink-0 text-warning-text" />
                <span className="min-w-0 flex-1">
                  <del className="text-fg-muted">{r.before}</del>
                  <br />
                  <ins className="font-medium no-underline">{r.after}</ins>
                </span>
                <Code id={r.id} />
              </li>
            ))}
            {removed.map((r) => (
              <li key={`r-${r.id}`} className="flex items-start gap-2.5 text-body">
                <Minus strokeWidth={1.75} aria-label="حذف شد" className="mt-2 size-4 shrink-0 text-danger-text" />
                <span className="min-w-0 flex-1">
                  <del className="text-fg-muted">{r.statement}</del>
                </span>
                <Code id={r.id} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
