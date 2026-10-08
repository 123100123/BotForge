import Link from "next/link";
import { Logo } from "@/components/app/logo";
import { ThemeMenu } from "@/components/app/theme-menu";
import { buttonVariants } from "@/components/ui/button";
import { NavMenu } from "./nav-menu";

export const SECTION_LINKS = [
  { href: "#capabilities", label: "قابلیت‌ها" },
  { href: "#how", label: "نحوهٔ کار" },
  { href: "#reports", label: "گزارش‌ها" },
];

export const CONTAINER = "mx-auto w-full max-w-[1360px] px-4 sm:px-6 lg:px-10";

/** Sticky 64px bar: mark, section anchors (a menu below 1024px), theme, and «ورود» as the one filled button. */
export function LandingNav() {
  return (
    <header className="sticky top-0 z-sticky border-b border-border bg-page">
      <div className={`${CONTAINER} flex h-16 items-center gap-3`}>
        <Link href="/" className="rounded-xs" aria-label="بات‌فورج، صفحهٔ اصلی">
          <Logo size={30} />
        </Link>
        <nav aria-label="بخش‌های صفحه" className="ms-8 hidden items-center gap-6 lg:flex">
          {SECTION_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="rounded-xs text-body text-fg-secondary transition-colors duration-fast hover:text-fg">
              {link.label}
            </a>
          ))}
        </nav>
        <div className="ms-auto flex items-center gap-1 sm:gap-2">
          <div className="lg:hidden">
            <NavMenu links={SECTION_LINKS} />
          </div>
          <ThemeMenu />
          <Link href="/login" className={buttonVariants({ variant: "primary" })}>
            ورود
          </Link>
        </div>
      </div>
    </header>
  );
}
