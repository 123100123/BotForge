import Link from "next/link";
import { Layers3 } from "lucide-react";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" aria-label="بات‌فورج، صفحهٔ اصلی" className="inline-flex shrink-0 items-center gap-2.5 rounded-xl text-[#15374a] outline-none focus-visible:ring-2 focus-visible:ring-[#0b91a3] dark:text-white">
      <span className="flex size-9 items-center justify-center rounded-xl bg-[#0f8ea4] text-white shadow-[0_8px_20px_-9px_rgba(15,142,164,.8)] sm:size-10"><Layers3 className="size-5" strokeWidth={2.5} /></span>
      <span className={`font-black tracking-tight ${compact ? "text-base" : "text-lg"}`}>بات‌فورج</span>
    </Link>
  );
}
