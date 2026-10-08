"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import { Button, buttonVariants } from "@heroui/react";
import { cn } from "@/lib/utils";

type ButtonLinkProps = ComponentProps<typeof Link> &
  Pick<ComponentProps<typeof Button>, "variant" | "size" | "fullWidth" | "isIconOnly">;

/** Anchor semantics and Next navigation with the exact HeroUI button styling. */
function ButtonLink({ className, variant = "primary", size = "md", fullWidth, isIconOnly, ...props }: ButtonLinkProps) {
  return (
    <Link
      className={cn(buttonVariants({ variant, size, fullWidth, isIconOnly }), className)}
      {...props}
    />
  );
}

export { Button, ButtonLink, buttonVariants };
