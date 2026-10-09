"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Check, Layers3, MessageCircleMore, Sparkles } from "lucide-react";
import { ThemeToggle } from "@/components/app/theme-toggle";
import { BrandMark } from "@/components/landing/brand-mark";
import { useAuth } from "@/lib/auth";
import { postLoginPath } from "@/lib/session-expiry";

/** Signed-in visitors return to the validated destination or the bot directory. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace(postLoginPath());
  }, [status, router]);

  return (
    <main className="min-h-dvh overflow-x-clip bg-[#f8faf8] text-[#17384b] dark:bg-[#091e30] dark:text-white">
      <div className="mx-auto grid min-h-dvh max-w-[1600px] lg:grid-cols-[1fr_.95fr]">
        <div className="relative flex min-w-0 flex-col px-5 pb-12 pt-5 sm:px-10 sm:pt-8 lg:px-[clamp(3rem,6vw,7rem)] lg:pb-20">
          <div className="flex items-center justify-between gap-3"><BrandMark /><ThemeToggle /></div>
          <div className="mx-auto flex w-full max-w-[440px] flex-1 flex-col justify-center pt-12 sm:pt-16 lg:pt-10">{children}</div>
          <p className="mx-auto mt-8 w-full max-w-[440px] text-xs leading-6 text-[#77909c] dark:text-[#8eafbb]">بات‌فورج · مرکز کنترل کسب‌وکار در تلگرام</p>
        </div>
        <aside className="relative hidden min-w-0 overflow-hidden bg-[#10344a] px-12 py-14 text-white lg:flex lg:flex-col lg:justify-between xl:px-20 dark:bg-[#071929]">
          <div aria-hidden="true" className="absolute -left-40 -top-44 size-[34rem] rounded-full border-[70px] border-[#197e91]/20" />
          <div aria-hidden="true" className="absolute -bottom-36 -right-32 size-[28rem] rounded-full bg-[#1a7c88]/20 blur-3xl" />
          <div className="relative flex items-center gap-2 text-xs font-bold tracking-wider text-[#8edbdd]"><Sparkles className="size-4" /> یک بستر برای ساخت و ادارهٔ ربات</div>
          <div className="relative max-w-xl py-16"><h2 className="text-4xl leading-[1.45] font-black xl:text-5xl">از یک توضیح شروع کنید. <span className="text-[#82dbdc]">بقیه را در کنترل داشته باشید.</span></h2><p className="mt-6 max-w-lg text-base leading-9 text-[#b5ced9]">بات‌فورج به شما کمک می‌کند ربات تلگرام کسب‌وکارتان را بسازید، قبل از انتشار امتحان کنید و بعد از یک پنل اداره کنید.</p>
            <div className="mt-12 max-w-md rounded-[1.8rem] border border-white/15 bg-white/10 p-5 shadow-2xl backdrop-blur-sm"><div className="flex items-center gap-3 border-b border-white/10 pb-4"><span className="flex size-10 items-center justify-center rounded-xl bg-[#47b9bd]/25 text-[#8ce2dc]"><MessageCircleMore className="size-5" /></span><div><p className="text-sm font-bold">ربات کارگاه</p><p className="text-xs text-[#a9c9d4]">نمایش نمونه با دادهٔ آزمایشی</p></div></div><p className="mt-5 rounded-2xl bg-[#24536a] px-4 py-3 text-sm leading-7 text-[#e0eff2]">«برای کارگاه‌ها ثبت‌نام بگیر و فهرست انتظار را مدیریت کن.»</p><div className="mt-4 flex items-center gap-2 text-xs text-[#9be1d9]"><Check className="size-4" /> آمادهٔ بررسی و آزمایش <ArrowLeft className="mr-auto size-4" /></div></div>
          </div>
          <div className="relative flex items-center gap-3 text-xs text-[#a9c8d3]"><Layers3 className="size-4" /> ساخت · آزمایش · انتشار · مدیریت</div>
        </aside>
      </div>
    </main>
  );
}
