import Link from "next/link";
import { cn } from "@/lib/utils";

const BASE = "flex-1 rounded-xs border border-transparent px-3 py-1.5 text-center text-small font-medium transition-colors duration-fast";

/**
 * «ورود | ساخت حساب»: two links (the routes stay /login and /signup). The typed email survives the switch
 * because both pages share the AuthShell state.
 */
export function AuthSwitch({ mode }: { mode: "login" | "signup" }) {
  return (
    <nav aria-label="ورود یا ساخت حساب" className="flex w-full gap-0.5 rounded-sm border border-border bg-surface-sunken p-0.5">
      <Link
        href="/login"
        aria-current={mode === "login" ? "page" : undefined}
        className={cn(BASE, mode === "login" ? "border-border bg-surface text-fg" : "text-fg-muted hover:text-fg")}
      >
        ورود
      </Link>
      <Link
        href="/signup"
        aria-current={mode === "signup" ? "page" : undefined}
        className={cn(BASE, mode === "signup" ? "border-border bg-surface text-fg" : "text-fg-muted hover:text-fg")}
      >
        ساخت حساب
      </Link>
    </nav>
  );
}
