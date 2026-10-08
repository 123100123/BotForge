"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ArrowLeft, Eye, EyeOff, Info, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authErrorMessage, useAuth } from "@/lib/auth";
import { IS_MOCK } from "@/lib/config";
import { postLoginPath } from "@/lib/session-expiry";

type Mode = "login" | "signup";
interface FieldErrors { email?: string; password?: string }
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD = 10;

function validate(mode: Mode, email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!email.trim()) errors.email = "ایمیل را وارد کنید.";
  else if (!EMAIL_RE.test(email.trim())) errors.email = "ایمیل واردشده معتبر نیست.";
  if (!password) errors.password = "گذرواژه را وارد کنید.";
  else if (mode === "signup" && password.length < MIN_PASSWORD) errors.password = "گذرواژه باید دست‌کم ۱۰ نویسه باشد.";
  return errors;
}

export function AuthForm({ mode }: { mode: Mode }) {
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const isLogin = mode === "login";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setNotice(null);
    const found = validate(mode, email, password);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setPending(true);
    try {
      if (isLogin) {
        await signIn(email.trim(), password);
        router.replace(postLoginPath());
      } else {
        const { needsConfirmation } = await signUp(email.trim(), password);
        if (needsConfirmation) setNotice("ثبت‌نام انجام شد. برای ادامه، پیوند تأییدی را که به ایمیل شما فرستادیم باز کنید.");
        else router.replace(postLoginPath());
      }
    } catch (err) {
      setFormError(authErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return <div className="w-full">
    <Link href="/" className="mb-9 inline-flex items-center gap-1.5 rounded-lg text-xs font-semibold text-[#6a8794] underline-offset-4 hover:text-[#128a9b] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0e91a3] dark:text-[#afcad4]"><ArrowLeft className="size-3.5 rotate-180" /> بازگشت به صفحهٔ اصلی</Link>
    <div className="mb-9"><span className="inline-flex items-center gap-2 rounded-full border border-[#d6e8e8] bg-[#eaf5f4] px-3 py-1.5 text-xs font-bold text-[#16848c] dark:border-[#275c67] dark:bg-[#143d4e] dark:text-[#8bdddb]"><ShieldCheck className="size-3.5" /> حساب بات‌فورج</span><h1 className="mt-5 text-3xl leading-[1.4] font-black text-[#14354a] sm:text-4xl dark:text-white">{isLogin ? "خوش آمدید." : "از همین‌جا شروع کنید."}</h1><p className="mt-3 text-sm leading-8 text-[#65808e] dark:text-[#acc5d0]">{isLogin ? "برای مدیریت ربات‌ها و کسب‌وکارتان وارد حساب خود شوید." : "یک حساب بسازید و اولین ربات کسب‌وکارتان را طراحی کنید."}</p></div>
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      <div><Label htmlFor="email" className="mb-2 block text-sm font-bold text-[#315267] dark:text-[#d2e4e9]">ایمیل</Label><div className="relative"><Mail aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-4 my-auto size-4 text-[#7b9ba9]" /><Input id="email" type="email" dir="ltr" autoComplete="email" inputMode="email" value={email} onChange={e => { setEmail(e.target.value); if (errors.email) setErrors(v => ({ ...v, email: undefined })); }} aria-invalid={Boolean(errors.email)} aria-describedby={errors.email ? "email-error" : undefined} placeholder="name@example.com" className="h-12 w-full rounded-xl border-[#d6e3e5] bg-white pr-11 pl-4 text-left text-sm text-[#17384b] shadow-sm placeholder:text-[#a2b4bc] focus-visible:border-[#158fa0] dark:border-[#2d5061] dark:bg-[#153349] dark:text-white dark:placeholder:text-[#7494a4]" /></div>{errors.email && <p id="email-error" className="mt-2 text-xs text-[#c84444] dark:text-[#ffaaa3]">{errors.email}</p>}</div>
      <div><div className="mb-2 flex items-center justify-between"><Label htmlFor="password" className="text-sm font-bold text-[#315267] dark:text-[#d2e4e9]">گذرواژه</Label>{!isLogin && <span className="text-xs text-[#7a929f] dark:text-[#98b8c4]">دست‌کم ۱۰ نویسه</span>}</div><div className="relative"><LockKeyhole aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-4 my-auto size-4 text-[#7b9ba9]" /><Input id="password" type={showPassword ? "text" : "password"} dir="ltr" autoComplete={isLogin ? "current-password" : "new-password"} value={password} onChange={e => { setPassword(e.target.value); if (errors.password) setErrors(v => ({ ...v, password: undefined })); }} aria-invalid={Boolean(errors.password)} aria-describedby={errors.password ? "password-error" : undefined} className="h-12 w-full rounded-xl border-[#d6e3e5] bg-white pr-11 pl-12 text-left text-sm text-[#17384b] shadow-sm focus-visible:border-[#158fa0] dark:border-[#2d5061] dark:bg-[#153349] dark:text-white" /><button type="button" onClick={() => setShowPassword(v => !v)} aria-label={showPassword ? "پنهان کردن گذرواژه" : "نمایش گذرواژه"} className="absolute inset-y-0 left-2 my-auto flex size-9 items-center justify-center rounded-lg text-[#6b8a99] hover:bg-[#ebf4f4] focus-visible:outline-2 focus-visible:outline-[#0e91a3] dark:hover:bg-white/10">{showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}</button></div>{errors.password && <p id="password-error" className="mt-2 text-xs text-[#c84444] dark:text-[#ffaaa3]">{errors.password}</p>}</div>
      {formError && <p role="alert" className="rounded-xl border border-[#f2cdca] bg-[#fff0ee] px-4 py-3 text-sm leading-7 text-[#b03d39] dark:border-[#75443f] dark:bg-[#472c32] dark:text-[#ffc5bc]">{formError}</p>}
      {notice && <p role="status" className="rounded-xl border border-[#bedfd5] bg-[#e9f8f1] px-4 py-3 text-sm leading-7 text-[#216c54] dark:border-[#2b6458] dark:bg-[#1d4b42] dark:text-[#a7ebcd]">{notice}</p>}
      <Button type="submit" variant="primary" size="lg" isDisabled={pending} isPending={pending} className="mt-2 w-full justify-center rounded-xl">{pending ? "لطفاً صبر کنید…" : isLogin ? "ورود به پنل" : "ساخت حساب کاربری"}{!pending && <ArrowLeft className="size-4" />}</Button>
    </form>
    {IS_MOCK && <div className="mt-6 flex items-start gap-3 rounded-xl border border-[#d7e9e9] bg-[#eff7f6] px-4 py-3 text-xs leading-6 text-[#547889] dark:border-[#275264] dark:bg-[#133747] dark:text-[#a7c8d3]"><Info className="mt-1 size-4 shrink-0 text-[#118ea0]" /><p><strong className="text-[#226878] dark:text-[#81d5d9]">حالت نمایشی:</strong> با هر ایمیل معتبر و گذرواژه‌ای می‌توانید وارد شوید. اطلاعات این حالت آزمایشی است.</p></div>}
    <p className="mt-8 border-t border-[#e3ebeb] pt-6 text-center text-sm text-[#6d8794] dark:border-white/10 dark:text-[#acc5d0]">{isLogin ? "هنوز حساب ندارید؟ " : "قبلاً حساب ساخته‌اید؟ "}<Link href={isLogin ? "/signup" : "/login"} className="font-bold text-[#087f94] underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0e91a3] dark:text-[#78d5dc]">{isLogin ? "ثبت‌نام کنید" : "وارد شوید"}</Link></p>
  </div>;
}
