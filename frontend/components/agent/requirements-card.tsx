import { Lightbulb, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fa } from "@/lib/format";
import type { Requirement, Requirements } from "@/lib/types";
import { REQUIREMENT_KIND_LABELS } from "./labels";

function RequirementRow({ item }: { item: Requirement }) {
  return (
    <li className="flex items-start gap-2 text-sm leading-7">
      <span dir="ltr" className="mt-1.5 inline-block shrink-0 rounded-xs bg-muted px-1.5 font-mono text-caption leading-5 text-muted-foreground">
        {item.id}
      </span>
      <span className="flex-1">{item.statement}</span>
      <Badge variant="outline" className="mt-1 shrink-0">
        {REQUIREMENT_KIND_LABELS[item.kind]}
      </Badge>
    </li>
  );
}

/** What the agent understood: confirmed requirements, assumptions, and what cannot be built. */
export function RequirementsCard({ requirements }: { requirements: Requirements }) {
  const confirmed = requirements.items.filter((r) => r.status === "confirmed");
  const assumed = requirements.items.filter((r) => r.status === "assumed");

  return (
    <Card>
      <CardHeader>
        <CardTitle>نیازمندی‌ها</CardTitle>
        <CardDescription className="leading-7">{requirements.business_summary}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {confirmed.length > 0 && (
          <section>
            <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              تأییدشده
              <Badge variant="success">{fa(confirmed.length)}</Badge>
            </h4>
            <ul className="flex flex-col gap-1.5">
              {confirmed.map((item) => (
                <RequirementRow key={item.id} item={item} />
              ))}
            </ul>
          </section>
        )}

        {assumed.length > 0 && (
          <section className="rounded-md border border-warning/30 bg-warning-soft p-3">
            <h4 className="mb-1 flex items-center gap-2 text-sm font-semibold">
              <Lightbulb className="size-4 text-warning-text" />
              فرض‌شده
              <Badge variant="warning">{fa(assumed.length)}</Badge>
            </h4>
            <p className="mb-2 text-caption text-muted-foreground">
              این موارد را خودم فرض کرده‌ام. اگر درست نیست، در گفتگو بگویید.
            </p>
            <ul className="flex flex-col gap-1.5">
              {assumed.map((item) => (
                <RequirementRow key={item.id} item={item} />
              ))}
            </ul>
          </section>
        )}

        {requirements.unsupported.length > 0 && (
          <section className="rounded-md border border-destructive/30 bg-danger-soft p-3">
            <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <TriangleAlert className="size-4 text-danger-text" />
              پشتیبانی نمی‌شود
              <Badge variant="destructive">{fa(requirements.unsupported.length)}</Badge>
            </h4>
            <ul className="flex flex-col gap-3">
              {requirements.unsupported.map((u, i) => (
                <li key={i} className="text-sm leading-7">
                  <div className="font-medium">{u.statement}</div>
                  <div className="text-muted-foreground">دلیل: {u.reason}</div>
                  {u.alternative && <div>جایگزین پیشنهادی: {u.alternative}</div>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </CardContent>
    </Card>
  );
}
