"use client";

import type { ReactNode } from "react";
import { useParams } from "next/navigation";
import { BusinessRoot } from "@/components/app/shell/business-root";

/**
 * The business layout: loads the business once and keeps it (and its agent run and assistant thread)
 * mounted while the owner moves between its sections.
 */
export default function BotLayout({ children }: { children: ReactNode }) {
  const { id } = useParams<{ id: string }>();
  return (
    <BusinessRoot key={id} botId={id}>
      {children}
    </BusinessRoot>
  );
}
