import type { ComponentProps } from "react";
import { Chip } from "@heroui/react";

type Tone = "default" | "secondary" | "outline" | "accent" | "success" | "warning" | "destructive";
type BadgeProps = Omit<ComponentProps<typeof Chip>, "color" | "variant"> & { variant?: Tone };

/** App status vocabulary rendered by HeroUI's Chip. */
function Badge({ variant = "secondary", ...props }: BadgeProps) {
  const color = variant === "success" ? "success" : variant === "warning" ? "warning" : variant === "destructive" ? "danger" : variant === "default" || variant === "accent" ? "accent" : "default";
  const chipVariant = variant === "outline" ? "tertiary" : variant === "default" ? "primary" : "soft";
  return <Chip color={color} variant={chipVariant} size="sm" {...props} />;
}

export { Badge };
