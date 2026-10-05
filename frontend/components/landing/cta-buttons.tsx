"use client";

import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

/**
 * The landing page's calls to action. Signed-in visitors get the dashboard link; everyone else
 * (including while the session is still being checked) gets sign-up and login.
 */
export function CtaButtons({ size = "lg", className }: { size?: "default" | "lg"; className?: string }) {
  const { status } = useAuth();

  if (status === "authenticated") {
    return (
      <div className={cn("flex flex-wrap gap-3", className)}>
        <Link href="/bots" className={buttonVariants({ size })}>
          رفتن به داشبورد
        </Link>
      </div>
    );
  }
  return (
    <div className={cn("flex flex-wrap gap-3", className)}>
      <Link href="/signup" className={buttonVariants({ size })}>
        شروع کنید
      </Link>
      <Link href="/login" className={buttonVariants({ size, variant: "outline" })}>
        ورود
      </Link>
    </div>
  );
}

/** Compact header button: «ورود / داشبورد». */
export function HeaderCta() {
  const { status } = useAuth();
  const signedIn = status === "authenticated";
  return (
    <Link href={signedIn ? "/bots" : "/login"} className={buttonVariants({ size: "sm", variant: signedIn ? "default" : "outline" })}>
      {signedIn ? "داشبورد" : "ورود"}
    </Link>
  );
}
