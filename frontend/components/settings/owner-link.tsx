"use client";

import { useState } from "react";
import { CircleCheck, CircleDashed, CircleSlash, ExternalLink, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { TelegramStatus } from "@/lib/types";
import { CopyButton, LinkBox, PanelSection, SettingsPanel } from "./settings-panel";

interface OwnerLinkProps {
  status: TelegramStatus;
  onRefresh: () => Promise<void>;
}

/** The deep link the owner opens in Telegram so alerts (new bookings, requests) reach them. */
export function OwnerLink({ status, onRefresh }: OwnerLinkProps) {
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  }

  // Three states once connected: linked, link ready, nothing to show. Not connected has no link yet.
  const badge = !status.connected ? (
    <StatusBadge tone="neutral" icon={<CircleSlash strokeWidth={1.75} aria-hidden />}>
      منتظر اتصال ربات
    </StatusBadge>
  ) : status.owner_linked ? (
    <StatusBadge tone="success" icon={<CircleCheck strokeWidth={1.75} aria-hidden />}>
      متصل است
    </StatusBadge>
  ) : status.owner_link ? (
    <StatusBadge tone="warning" icon={<CircleDashed strokeWidth={1.75} aria-hidden />}>
      هنوز متصل نشده
    </StatusBadge>
  ) : (
    <StatusBadge tone="neutral" icon={<CircleSlash strokeWidth={1.75} aria-hidden />}>
      پیوندی در دسترس نیست
    </StatusBadge>
  );

  return (
    <SettingsPanel
      title="دریافت اعلان‌ها در تلگرام"
      description="با باز کردن پیوند زیر در تلگرام، شما مدیر ربات می‌شوید و ثبت‌نام‌ها و درخواست‌های جدید را همان‌جا می‌گیرید."
      status={badge}
    >
      {!status.connected ? (
        <PanelSection>
          <p className="text-small text-fg-secondary">
            پس از اتصال ربات به تلگرام (پنل بالا)، پیوند دریافت اعلان‌ها ساخته و اینجا نمایش داده می‌شود.
          </p>
        </PanelSection>
      ) : status.owner_linked ? (
        // No link while an owner is linked: the code was used, and a code never replaces a linked
        // owner. Disconnecting unlinks the owner; the next connect returns a fresh link.
        <PanelSection>
          <p role="status" className="rounded-sm bg-success-soft p-3 text-small text-success-text">
            حساب تلگرام شما به‌عنوان مدیر متصل است و اعلان‌ها را همان‌جا دریافت می‌کنید.
          </p>
          <p className="max-w-prose text-small text-fg-secondary">
            پیوند دریافت اعلان فقط یک بار قابل استفاده است. برای دریافت اعلان‌ها در حساب تلگرام دیگری، اتصال ربات را قطع کنید و توکن را
            دوباره وارد کنید. با قطع اتصال، این حساب هم از مدیریت ربات جدا می‌شود و پس از اتصال دوباره، پیوند تازه‌ای همین‌جا نمایش داده
            می‌شود که باید آن را با حساب جدید باز کنید.
          </p>
        </PanelSection>
      ) : !status.owner_link ? (
        <PanelSection>
          <p className="text-small text-fg-secondary">
            الان پیوندی در دسترس نیست. با وارد کردن دوبارهٔ توکن ربات (پس از قطع اتصال)، یک پیوند تازه ساخته می‌شود.
          </p>
        </PanelSection>
      ) : (
        <PanelSection title="پیوند شما">
          <LinkBox value={status.owner_link} />
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <a href={status.owner_link} target="_blank" rel="noreferrer">
                <ExternalLink strokeWidth={1.75} />
                باز کردن در تلگرام
              </a>
            </Button>
            <CopyButton value={status.owner_link} />
            <Button variant="ghost" onClick={() => void refresh()} loading={refreshing}>
              <RefreshCw strokeWidth={1.75} />
              بررسی وضعیت
            </Button>
          </div>
          <p className="max-w-prose text-small text-fg-secondary">
            پیوند را فقط خودتان باز کنید: نخستین حسابی که آن را باز کند مدیر ربات می‌شود و اعلان‌ها را دریافت می‌کند. پیوند فقط یک بار
            کار می‌کند.
          </p>
        </PanelSection>
      )}
    </SettingsPanel>
  );
}
