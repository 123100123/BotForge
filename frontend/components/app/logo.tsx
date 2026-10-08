import { cn } from "@/lib/utils";

/**
 * BotForge mark: a brand tile holding a light square with a notch cut from its end-bottom corner.
 * Pure inline SVG using tokens (follows the theme). `size` is the tile edge in px.
 */
export function Logo({
  size = 28,
  withWordmark = true,
  className,
}: {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        role={withWordmark ? undefined : "img"}
        aria-label={withWordmark ? undefined : "بات‌فورج"}
        aria-hidden={withWordmark ? true : undefined}
        className="shrink-0"
      >
        <rect width="32" height="32" rx="8" fill="var(--brand)" />
        <rect x="8" y="8" width="16" height="16" rx="3" fill="var(--on-brand)" />
        <rect x="16" y="16" width="8" height="8" rx="1.5" fill="var(--brand)" />
      </svg>
      {withWordmark && (
        <span className="font-extrabold text-fg" style={{ fontSize: Math.round(size * 0.64), lineHeight: 1.2 }}>
          بات‌فورج
        </span>
      )}
    </span>
  );
}
