import type { ReactNode } from "react";
import { AuthBrandPanel } from "@/components/auth/auth-brand-panel";
import { AuthShell } from "@/components/auth/auth-shell";

/** Split shell for the auth pages (form at the start edge, brand panel at the end edge from 1024px). */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return <AuthShell aside={<AuthBrandPanel />}>{children}</AuthShell>;
}
