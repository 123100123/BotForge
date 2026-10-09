"use client";

import { ArrowLeft } from "lucide-react";
import { ButtonLink } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

/** The same destination is used in the hero and final call to action. */
export function CtaButtons({ className }: { className?: string }) {
  const { status } = useAuth();
  const signedIn = status === "authenticated";

  return <div className={cn("flex flex-wrap items-center gap-3", className)}>
    <ButtonLink href={signedIn ? "/bots" : "/signup"} variant="primary" size="lg" className="rounded-xl shadow-[0_13px_26px_-15px_rgba(0,105,134,.65)]">{signedIn ? "رفتن به داشبورد" : "ساخت ربات را شروع کنید"}<ArrowLeft className="size-4" /></ButtonLink>
    {!signedIn && <ButtonLink href="/login" variant="outline" size="lg" className="rounded-xl">حساب دارم</ButtonLink>}
  </div>;
}

export function HeaderCta() {
  const { status } = useAuth();
  const signedIn = status === "authenticated";
  return <ButtonLink href={signedIn ? "/bots" : "/login"} variant="outline" size="sm" className="rounded-xl whitespace-nowrap">{signedIn ? "داشبورد" : "ورود"}</ButtonLink>;
}
