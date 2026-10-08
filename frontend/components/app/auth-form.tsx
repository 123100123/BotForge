"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { AuthSwitch } from "@/components/auth/auth-switch";
import { useAuthShell } from "@/components/auth/auth-shell";
import { PasswordField } from "@/components/auth/password-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";
import { IS_MOCK } from "@/lib/config";
import { ApiError } from "@/lib/errors";
import { fa } from "@/lib/format";

type Mode = "login" | "signup";

interface FieldErrors {
  email?: string;
  password?: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD = 10;
const GENERIC_ERROR = "ورود یا ثبت‌نام انجام نشد. دوباره امتحان کنید.";
const SIGNUP_CLOSED = "ثبت‌نام در حال حاضر بسته است.";

function validate(mode: Mode, email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!email.trim()) errors.email = "ایمیل را وارد کنید.";
  else if (!EMAIL_RE.test(email.trim())) errors.email = "ایمیل معتبر نیست. نمونه: name@example.com";
  if (!password) errors.password = "گذرواژه را وارد کنید.";
  else if (mode === "signup" && password.length < MIN_PASSWORD) {
    errors.password = `گذرواژه دست‌کم ${fa(MIN_PASSWORD)} نویسه باشد. الان ${fa(password.length)} نویسه است.`;
  }
  return errors;
}

/** What a failed request means for the form: a field message, "signup is closed", or a general message. */
function explain(mode: Mode, err: unknown): { field?: FieldErrors; closed?: boolean; general?: string } {
  if (!(err instanceof ApiError)) return { general: GENERIC_ERROR };
  if (mode === "signup" && (err.status === 403 || err.code === "signup_disabled")) return { closed: true };
  switch (err.code) {
    case "invalid_email":
      return { field: { email: "ایمیل معتبر نیست. نمونه: name@example.com" } };
    case "weak_password":
      return { field: { password: `گذرواژه دست‌کم ${fa(MIN_PASSWORD)} نویسه باشد.` } };
    case "email_taken":
      return { field: { email: "با این ایمیل قبلاً حساب ساخته شده است. ایمیل دیگری بنویسید یا وارد شوید." } };
    case "invalid_credentials":
      return { general: "ایمیل یا گذرواژه درست نیست. دوباره امتحان کنید." };
    case "rate_limited":
      return { general: "تعداد تلاش‌ها زیاد بود. کمی بعد دوباره امتحان کنید." };
    case "network_error":
      return { general: err.message };
    default:
      return { general: GENERIC_ERROR };
  }
}

export function AuthForm({ mode }: { mode: Mode }) {
  const { signIn, signUp } = useAuth();
  const { email, setEmail, setAfterAuth } = useAuthShell();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [closed, setClosed] = useState(false);
  const [pending, setPending] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const isLogin = mode === "login";

  function showErrors(found: FieldErrors) {
    setErrors(found);
    if (found.email) emailRef.current?.focus();
    else if (found.password) passwordRef.current?.focus();
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    const found = validate(mode, email, password);
    showErrors(found);
    if (Object.keys(found).length > 0) return;

    setPending(true);
    try {
      if (isLogin) {
        await signIn(email.trim(), password);
        router.replace("/bots");
      } else {
        // The shell's redirect for any new session would pick /bots; a new account starts at onboarding.
        setAfterAuth("/bots/new");
        await signUp(email.trim(), password);
        router.replace("/bots/new");
      }
    } catch (err) {
      setAfterAuth("/bots");
      const result = explain(mode, err);
      if (result.closed) setClosed(true);
      if (result.field) showErrors(result.field);
      else setErrors({});
      setFormError(result.general ?? null);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <AuthSwitch mode={mode} />

      <div className="flex flex-col gap-1">
        <h1 className="text-h1 text-fg">{isLogin ? "ورود به بات‌فورج" : "ساخت حساب"}</h1>
        <p className="text-body text-fg-secondary">
          {isLogin ? "برای مدیریت کسب‌وکارتان وارد شوید." : "با ایمیل و گذرواژه شروع کنید. کسب‌وکارتان را در قدم بعد توضیح می‌دهید."}
        </p>
      </div>

      {closed && (
        <p role="alert" className="rounded-sm bg-warning-soft px-3 py-2.5 text-small text-warning-text">
          {SIGNUP_CLOSED} اگر حساب دارید{" "}
          <Link href="/login" className="font-medium underline underline-offset-4">
            وارد شوید
          </Link>
          .
        </p>
      )}

      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <Label htmlFor="email">ایمیل</Label>
          <Input
            ref={emailRef}
            id="email"
            name="email"
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
            <p id="email-error" className="text-caption text-danger-text">
              {errors.email}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="password">گذرواژه</Label>
          <PasswordField
            ref={passwordRef}
            id="password"
            name="password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={Boolean(errors.password)}
            aria-describedby={[!isLogin ? "password-hint" : null, errors.password ? "password-error" : null].filter(Boolean).join(" ") || undefined}
          />
          {!isLogin && (
            <p id="password-hint" className="text-caption text-fg-muted">
              دست‌کم {fa(MIN_PASSWORD)} نویسه.
            </p>
          )}
          {errors.password && (
            <p id="password-error" className="text-caption text-danger-text">
              {errors.password}
            </p>
          )}
        </div>

        {formError && (
          <p role="alert" className="rounded-sm bg-danger-soft px-3 py-2.5 text-small text-danger-text">
            {formError}
          </p>
        )}

        <Button type="submit" size="lg" loading={pending} disabled={closed} className="w-full">
          {isLogin ? "ورود" : "ساخت حساب"}
        </Button>

        {IS_MOCK && (
          <p className="text-caption text-fg-muted">
            حالت نمایشی: ورود با هر ایمیل و گذرواژه‌ای ممکن است و همه‌چیز با دادهٔ آزمایشی اجرا می‌شود.
          </p>
        )}
      </form>
    </div>
  );
}
