"use client";

import { LogOut } from "lucide-react";
import { useSignOut } from "@/components/app/account-menu";
import { ThemeChoice } from "@/components/app/theme-choice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";

/** Settings › Account: who is signed in, the theme, and signing out. */
export function AccountSettings() {
  const { user } = useAuth();
  const signOut = useSignOut();
  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader>
          <h2 className="text-h3 text-fg">حساب کاربری</h2>
          <CardDescription>با این ایمیل وارد شده‌اید.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col items-start gap-4">
          <p dir="ltr" className="text-body text-fg">
            {user?.email ?? "—"}
          </p>
          <Button variant="secondary" onClick={() => void signOut()}>
            <LogOut className="rtl:-scale-x-100" strokeWidth={1.75} />
            خروج از حساب
          </Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="text-h3 text-fg">ظاهر</h2>
          <CardDescription>پوستهٔ روشن یا تیره، یا هماهنگ با تنظیمات دستگاه.</CardDescription>
        </CardHeader>
        <CardContent>
          <ThemeChoice className="max-w-md" />
        </CardContent>
      </Card>
    </div>
  );
}
