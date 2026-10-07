import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Shown instead of the app when real mode (NEXT_PUBLIC_MOCK is not "1") is missing required
 * variables. Meant for the operator of the deployment, not the bot owner.
 */
export function ConfigError({ missing }: { missing: string[] }) {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-10">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle className="text-lg">پیکربندی بات‌فورج کامل نیست</CardTitle>
          <CardDescription className="leading-7">
            این نسخه برای اتصال به سرور واقعی ساخته شده، اما متغیرهای محیطی زیر خالی هستند. بدون آن‌ها ورود به
            حساب ممکن نیست.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm leading-7">
          <ul className="flex flex-col gap-1 rounded-md bg-destructive/10 p-3 text-destructive">
            {missing.map((name) => (
              <li key={name} dir="ltr" className="text-start font-mono">
                {name}
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground">
            این متغیرها را در تنظیمات محیطی میزبان (مثلاً Netlify یا Vercel) وارد کنید و دوباره بسازید و منتشر کنید؛
            مقدارهای NEXT_PUBLIC هنگام ساخت در برنامه قرار می‌گیرند. برای اجرای نمایشی با دادهٔ آزمایشی،
            NEXT_PUBLIC_MOCK=1 را تنظیم کنید.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
