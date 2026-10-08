import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// The type-scale utilities (text-h1, text-body ...) are font sizes, not colors: tell tailwind-merge so
// `cn("text-h1", "text-fg-muted")` keeps both, and `cn("text-h1", "text-sm")` keeps the last.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["display", "h1", "h2", "h3", "body", "small", "caption", "metric", "metric-sm"] }],
      shadow: [{ shadow: ["float"] }],
      "border-color": [{ border: ["float"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
