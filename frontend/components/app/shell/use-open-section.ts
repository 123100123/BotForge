"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback } from "react";
import { useOptionalBusiness } from "@/components/app/business-context";
import { sectionHref, type SectionHrefOptions, type SectionTarget } from "@/lib/routes";

/**
 * Cross-links between sections: `openSection("capabilities")` navigates to that section's route of the
 * current business. Legacy names (copilot, agent, data, simulator) are mapped by `sectionHref`; "data"
 * goes to the business's first Operations route.
 */
export function useOpenSection(): (section: SectionTarget, opts?: SectionHrefOptions) => void {
  const router = useRouter();
  const params = useParams<{ id?: string }>();
  const business = useOptionalBusiness();
  const botId = business?.bot.id ?? params.id ?? null;
  const operationsHref = business?.operationsHref ?? null;

  return useCallback(
    (section: SectionTarget, opts?: SectionHrefOptions) => {
      if (!botId) return;
      router.push(sectionHref(botId, section, { operationsHref, ...opts }));
    },
    [router, botId, operationsHref],
  );
}
