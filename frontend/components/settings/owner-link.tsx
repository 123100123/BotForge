"use client";

import { useEffect, useRef, useState } from "react";
import { Bell, Check, Copy, ExternalLink, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { TelegramStatus } from "@/lib/types";

interface OwnerLinkProps {
  status: TelegramStatus;
  onRefresh: () => Promise<void>;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** The deep link the owner opens in Telegram so alerts (new bookings, requests) reach them. */
export function OwnerLink({ status, onRefresh }: OwnerLinkProps) {
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    if (!status.owner_link) return;
    setCopied((await copyText(status.owner_link)) ? "yes" : "no");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(null), 2500);
  }

  async function refresh() {
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="size-5 text-muted-foreground" />
          دریافت اعلان‌ها در تلگرام
          {status.connected && (
            <Badge variant={status.owner_linked ? "success" : "warning"} className="ms-auto">
              {status.owner_linked ? "متصل شد" : "هنوز متصل نشده"}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          با باز کردن پیوند زیر در تلگرام، شما مدیر ربات می‌شوید و ثبت‌نام‌ها و درخواست‌های جدید را همان‌جا می‌گیرید.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!status.connected ? (
          <p className="text-sm leading-7 text-muted-foreground">
            پس از اتصال ربات به تلگرام (کادر بالا)، پیوند دریافت اعلان‌ها ساخته و اینجا نمایش داده می‌شود.
          </p>
        ) : status.owner_linked ? (
          // No link while an owner is linked: the code was used, and a code never replaces a linked
          // owner. Disconnecting unlinks the owner; the next connect returns a fresh link (shown below).
          <div className="flex flex-col gap-3">
            <p role="status" className="flex items-start gap-2 rounded-md bg-success/10 p-3 text-sm leading-7 text-success">
              <Check className="mt-1.5 size-4 shrink-0" />
              حساب تلگرام شما به‌عنوان مدیر متصل است و اعلان‌ها را همان‌جا دریافت می‌کنید.
            </p>
            <p className="text-sm leading-7 text-muted-foreground">
              پیوند دریافت اعلان فقط یک بار قابل استفاده است. برای دریافت اعلان‌ها در حساب تلگرام دیگری، اتصال ربات را قطع کنید و توکن را
              دوباره وارد کنید. با قطع اتصال، این حساب هم از مدیریت ربات جدا می‌شود و پس از اتصال دوباره، پیوند تازه‌ای همین‌جا نمایش داده
              می‌شود که باید آن را با حساب جدید باز کنید.
            </p>
          </div>
        ) : !status.owner_link ? (
          <p className="text-sm leading-7 text-muted-foreground">
            الان پیوندی در دسترس نیست. با وارد کردن دوبارهٔ توکن ربات (پس از قطع اتصال)، یک پیوند تازه ساخته می‌شود.
          </p>
        ) : (
          <>
            <div className="rounded-md border bg-surface-secondary/40 p-3 text-sm break-all" dir="ltr">
              {status.owner_link}
            </div>
            <div className="flex flex-wrap gap-2">

                <a href={status.owner_link} target="_blank" rel="noreferrer" className={buttonVariants({ variant: "primary" })}>
                  <ExternalLink />
                  باز کردن در تلگرام
                </a>
              <Button variant="outline" onPress={copy}>
                {copied === "yes" ? <Check /> : <Copy />}
                {copied === "yes" ? "کپی شد" : "کپی پیوند"}
              </Button>
              <Button variant="ghost" onPress={refresh} isDisabled={refreshing}>
                <RefreshCw className={refreshing ? "animate-spin" : undefined} />
                بررسی وضعیت
              </Button>
            </div>
            {copied === "no" && <p role="status" className="text-sm text-destructive">کپی خودکار انجام نشد؛ پیوند را دستی انتخاب و کپی کنید.</p>}
            <p className="text-sm leading-7 text-muted-foreground">
              پیوند را فقط خودتان باز کنید: نخستین حسابی که آن را باز کند مدیر ربات می‌شود و اعلان‌ها را دریافت می‌کند. پیوند فقط یک بار
              کار می‌کند.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
