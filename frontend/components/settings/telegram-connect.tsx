"use client";

import { useState, type FormEvent } from "react";
import { CircleCheck, CircleSlash, ExternalLink, Unplug } from "lucide-react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { TelegramStatus } from "@/lib/types";
import { DANGER_OUTLINE, FieldRow, PanelSection, SettingsPanel } from "./settings-panel";

interface TelegramConnectProps {
  botId: string;
  status: TelegramStatus;
  hasActiveRevision: boolean;
  onChanged: (status: TelegramStatus) => void;
}

/** Settings › Telegram › connection: status, bot username and link, the connect form, and disconnect. */
export function TelegramConnect({ botId, status, hasActiveRevision, onChanged }: TelegramConnectProps) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  async function connect(e: FormEvent) {
    e.preventDefault();
    const value = token.trim();
    if (!value) {
      setError("توکن ربات را وارد کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await api.connectTelegram(botId, value);
      setToken(""); // the token is never kept after a successful request
      onChanged(next);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPanel
      title="اتصال به تلگرام"
      description="مشتری‌ها از طریق ربات تلگرام خودتان با کسب‌وکار شما صحبت می‌کنند."
      status={
        status.connected ? (
          <StatusBadge tone="success" icon={<CircleCheck strokeWidth={1.75} aria-hidden />}>
            وصل است
          </StatusBadge>
        ) : (
          <StatusBadge tone="neutral" icon={<CircleSlash strokeWidth={1.75} aria-hidden />}>
            وصل نیست
          </StatusBadge>
        )
      }
    >
      {status.last_error && (
        <PanelSection>
          <ErrorNote>آخرین خطا: {status.last_error}</ErrorNote>
        </PanelSection>
      )}

      {status.connected ? (
        <>
          <PanelSection>
            <dl className="flex flex-col gap-3">
              <FieldRow label="نام کاربری ربات">
                <span dir="ltr" className="inline-block">
                  @{status.username}
                </span>
              </FieldRow>
              {status.bot_link && (
                <FieldRow label="پیوند ربات">
                  <a
                    href={status.bot_link}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex max-w-full items-center gap-1.5 rounded-xs text-brand-text hover:underline"
                  >
                    <span dir="ltr" className="min-w-0 break-all">
                      {status.bot_link}
                    </span>
                    <ExternalLink className="size-4 shrink-0" strokeWidth={1.75} aria-hidden />
                    <span className="sr-only">(باز می‌شود در تب جدید)</span>
                  </a>
                </FieldRow>
              )}
            </dl>
            {!hasActiveRevision && (
              <p role="status" className="rounded-sm bg-warning-soft p-3 text-small text-warning-text">
                ربات هنوز نسخهٔ فعالی ندارد و به مشتری‌ها «آماده نیست» را نشان می‌دهد. نسخهٔ ربات را در بخش «تغییرات» تأیید کنید.
              </p>
            )}
          </PanelSection>
          <PanelSection
            tone="danger"
            title="قطع اتصال"
            description="ربات دیگر به پیام‌های مشتری‌ها پاسخ نمی‌دهد. داده‌ها و نسخه‌های ربات حفظ می‌شود."
          >
            <div>
              <Button variant="secondary" className={DANGER_OUTLINE} onClick={() => setConfirmOpen(true)}>
                <Unplug strokeWidth={1.75} />
                قطع اتصال از تلگرام
              </Button>
            </div>
          </PanelSection>
          <ConfirmDialog
            open={confirmOpen}
            onOpenChange={setConfirmOpen}
            title="قطع اتصال از تلگرام"
            description="ربات دیگر به پیام‌های مشتری‌ها پاسخ نمی‌دهد و حساب تلگرام مدیر هم از ربات جدا می‌شود. داده‌ها و نسخه‌های ربات حفظ می‌شود. پس از اتصال دوباره، پیوند تازهٔ دریافت اعلان‌ها را در تلگرام باز کنید."
            confirmLabel="قطع اتصال"
            destructive
            onConfirm={async () => onChanged(await api.disconnectTelegram(botId))}
          />
        </>
      ) : (
        <PanelSection title="اتصال ربات">
          <form onSubmit={connect} noValidate className="flex flex-col gap-4">
            <ol className="list-[persian] space-y-1 ps-5 text-body text-fg-secondary">
              <li>
                در تلگرام با <span dir="ltr">@BotFather</span> گفتگو را شروع کنید.
              </li>
              <li>
                دستور <span dir="ltr">/newbot</span> را بفرستید و نام و نام کاربری ربات را انتخاب کنید.
              </li>
              <li>توکنی که BotFather می‌فرستد را کپی کنید و در کادر زیر بچسبانید.</li>
            </ol>
            <div className="grid max-w-md gap-1.5">
              <Label htmlFor="tg-token">توکن ربات</Label>
              <Input
                id="tg-token"
                type="password"
                dir="ltr"
                autoComplete="off"
                spellCheck={false}
                placeholder="123456789:AA…"
                className="text-start"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? "tg-token-help tg-token-error" : "tg-token-help"}
              />
              <p id="tg-token-help" className="text-caption text-fg-muted">
                توکن مثل یک رمز است: آن را فقط همین‌جا وارد کنید و برای کسی نفرستید.
              </p>
            </div>
            {error && (
              <ErrorNote>
                <span id="tg-token-error">{error}</span>
              </ErrorNote>
            )}
            <div>
              <Button type="submit" loading={busy}>
                {busy ? "در حال اتصال…" : "اتصال"}
              </Button>
            </div>
          </form>
        </PanelSection>
      )}
    </SettingsPanel>
  );
}
