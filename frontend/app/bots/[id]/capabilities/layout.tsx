"use client";

import type { ReactNode } from "react";
import { CapabilitiesProvider } from "@/components/capabilities/capabilities-provider";

/** The Capability Center list and detail routes share one capability list and one consequence sheet. */
export default function CapabilitiesLayout({ children }: { children: ReactNode }) {
  return <CapabilitiesProvider>{children}</CapabilitiesProvider>;
}
