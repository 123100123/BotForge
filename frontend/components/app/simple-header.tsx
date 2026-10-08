import Link from "next/link";
import { AccountMenu } from "@/components/app/account-menu";
import { Logo } from "@/components/app/logo";
import { ThemeMenu } from "@/components/app/theme-menu";

/** Header of the pages outside a business (/bots, /bots/new): the mark, the theme and the account menu. */
export function SimpleHeader() {
  return (
    <header className="border-b bg-surface">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-4">
        <Link href="/bots?all=1" aria-label="بات‌فورج: کسب‌وکارهای شما" className="rounded-xs">
          <Logo size={26} />
        </Link>
        <div className="flex items-center gap-1">
          <ThemeMenu />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
