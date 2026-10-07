"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";
import { IS_MOCK } from "@/lib/config";
import { errorMessage } from "@/lib/errors";
import { postLoginPath } from "@/lib/session-expiry";

type Mode = "login" | "signup";

interface FieldErrors {
  email?: string;
  password?: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD = 8;

function validate(mode: Mode, email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!email.trim()) errors.email = "ایمیل را وارد کنید.";
  else if (!EMAIL_RE.test(email.trim())) errors.email = "ایمیل واردشده معتبر نیست.";
  if (!password) errors.password = "گذرواژه را وارد کنید.";
  else if (mode === "signup" && password.length < MIN_PASSWORD) {
    errors.password = "گذرواژه باید دست‌کم ۸ نویسه باشد.";
  }
  return errors;
}

export function AuthForm({ mode }: { mode: Mode }) {
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
        if (needsConfirmation) {
          setNotice("ثبت‌نام انجام شد. برای ادامه، پیوند تأییدی که به ایمیل شما فرستادیم را باز کنید.");
        } else {
          router.replace(postLoginPath());
        }
      }
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="text-lg">{isLogin ? "ورود به بات‌فورج" : "ساخت حساب کاربری"}</CardTitle>
        <CardDescription>
          {isLogin ? "برای مدیریت رباتتان وارد شوید." : "با ایمیل و گذرواژه ثبت‌نام کنید."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">ایمیل</Label>
            <Input
              id="email"
              type="email"
              dir="ltr"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? "email-error" : undefined}
              className="text-start"
            />
            {errors.email && (
              <p id="email-error" className="text-xs text-destructive">
                {errors.email}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">گذرواژه</Label>
            <Input
              id="password"
              type="password"
              dir="ltr"
              autoComplete={isLogin ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={Boolean(errors.password)}
              aria-describedby={errors.password ? "password-error" : undefined}
              className="text-start"
            />
            {errors.password && (
              <p id="password-error" className="text-xs text-destructive">
                {errors.password}
              </p>
            )}
          </div>

          {formError && (
            <p role="alert" className="rounded-md bg-destructive/10 p-2.5 text-sm text-destructive">
              {formError}
            </p>
          )}
          {notice && (
            <p role="status" className="rounded-md bg-success/10 p-2.5 text-sm text-success">
              {notice}
            </p>
          )}

          <Button type="submit" disabled={pending}>
            {pending ? "لطفاً صبر کنید…" : isLogin ? "ورود" : "ثبت‌نام"}
          </Button>

          {IS_MOCK && (
            <p className="text-xs leading-6 text-muted-foreground">
              حالت نمایشی: با هر ایمیل و گذرواژه‌ای می‌توانید وارد شوید و همه‌چیز با دادهٔ آزمایشی اجرا می‌شود.
            </p>
          )}

          <p className="text-center text-sm text-muted-foreground">
            {isLogin ? "حساب کاربری ندارید؟ " : "قبلاً ثبت‌نام کرده‌اید؟ "}
            <Link href={isLogin ? "/signup" : "/login"} className="font-medium text-primary hover:underline">
              {isLogin ? "ثبت‌نام" : "ورود"}
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
