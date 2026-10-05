"use client";

import { EmptyState, ErrorNote, LoadingBlock } from "@/components/app/state-blocks";
import { useLoader } from "@/components/app/use-loader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { Bot } from "@/lib/types";

/** Capability Center (stub): categories with their capabilities and on/off state. W1-FE-CC adds toggles and plans. */
export function CapabilitiesTab({ bot }: { bot: Bot }) {
  const { data, error } = useLoader(() => api.listCapabilities(bot.id), bot.id);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <LoadingBlock />;

  const categories = data.categories.filter((c) => c.capabilities.length > 0);
  if (categories.length === 0) {
    return (
      <EmptyState title="قابلیتی در دسترس نیست">
        فهرست قابلیت‌های کسب‌وکار پس از ساخت ربات اینجا نمایش داده می‌شود.
      </EmptyState>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {categories.map((category) => (
        <section key={category.id} aria-label={category.name} className="flex flex-col gap-3">
          <h2 className="text-base font-semibold">{category.name}</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {category.capabilities.map((c) => (
              <Card key={c.id} className="gap-2 py-4">
                <CardHeader className="flex-row items-center justify-between gap-2">
                  <CardTitle className="text-sm">{c.name}</CardTitle>
                  <Badge variant={c.enabled ? "success" : "secondary"}>{c.enabled ? "فعال" : "غیرفعال"}</Badge>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-7 text-muted-foreground">{c.description}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
