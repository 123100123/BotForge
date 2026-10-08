import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import type { AnalysisProfileOut } from "@/lib/types";
import { checkSentence, metricSentence } from "./describe";

function SentenceList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-small text-fg-muted">{empty}</p>;
  return (
    <ul className="flex list-disc flex-col gap-1.5 ps-5 text-body text-fg marker:text-fg-muted">
      {items.map((s) => (
        <li key={s}>{s}</li>
      ))}
    </ul>
  );
}

/**
 * What a profile will do, as plain sentences: what is measured, what is checked, which columns the file must
 * have. Built from the profile's spec; the spec itself (fields, measures) is never shown.
 */
export function ProfileSummary({ profile, children }: { profile: AnalysisProfileOut; children?: ReactNode }) {
  const columns = profile.expected_columns ?? [];
  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <h3 className="text-h3 text-fg">چه چیزی اندازه‌گیری می‌شود</h3>
        <SentenceList items={(profile.metrics ?? []).map(metricSentence)} empty="شاخصی تعریف نشده است." />
      </section>
      <section className="flex flex-col gap-2">
        <h3 className="text-h3 text-fg">چه چیزی بررسی می‌شود</h3>
        <SentenceList items={(profile.checks ?? []).map(checkSentence)} empty="هشداری تعریف نشده است." />
      </section>
      {columns.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-h3 text-fg">ستون‌های مورد انتظار</h3>
          <ul aria-label="ستون‌های مورد انتظار" className="flex flex-wrap gap-1.5">
            {columns.map((c) => (
              <li key={c}>
                <Badge variant="outline">
                  <bdi>{c}</bdi>
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}
      {children}
    </div>
  );
}
