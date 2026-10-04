"use client";

import { useState, type FormEvent } from "react";
import { ExternalLink, Send, Unplug } from "lucide-react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { ErrorNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { TelegramStatus } from "@/lib/types";

interface TelegramConnectProps {
  botId: string;
  status: TelegramStatus;
  hasActiveRevision: boolean;
  onChanged: (status: TelegramStatus) => void;
}

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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Send className="size-5 text-muted-foreground" />
          اتصال به تلگرام
          <Badge variant={status.connected ? "success" : "secondary"} className="ms-auto">
            {status.connected ? "وصل است" : "وصل نیست"}
          </Badge>
        </CardTitle>
        <CardDescription>مشتری‌ها از طریق ربات تلگرام خودتان با کسب‌وکار شما صحبت می‌کنند.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {status.last_error && <ErrorNote>آخرین خطا: {status.last_error}</ErrorNote>}

        {status.connected ? (
          <>
            <dl className="grid gap-3 text-sm sm:grid-cols-[auto_1fr] sm:gap-x-6">
              <dt className="text-muted-foreground">نام کاربری ربات</dt>
              <dd>
                <span dir="ltr">@{status.username}</span>
              </dd>
              {status.bot_link && (
                <>
                  <dt className="text-muted-foreground">پیوند ربات</dt>
                  <dd>
                    <a href={status.bot_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                      <span dir="ltr">{status.bot_link}</span>
                      <ExternalLink className="size-3.5" />
                    </a>
                  </dd>
                </>
              )}
            </dl>
            {!hasActiveRevision && (
              <p className="rounded-md bg-warning/15 p-3 text-sm leading-7 text-warning">
                ربات هنوز نسخهٔ فعالی ندارد و به مشتری‌ها «آماده نیست» را نشان می‌دهد. نسخهٔ ربات را در تب ایجنت تأیید کنید.
              </p>
            )}
            <div>
              <Button variant="outline" onClick={() => setConfirmOpen(true)}>
                <Unplug />
                قطع اتصال
              </Button>
            </div>
            <ConfirmDialog
              open={confirmOpen}
              onOpenChange={setConfirmOpen}
              title="قطع اتصال از تلگرام"
              description="ربات دیگر به پیام‌های مشتری‌ها پاسخ نمی‌دهد. داده‌ها و نسخه‌های ربات حفظ می‌شود و می‌توانید دوباره وصل کنید."
              confirmLabel="قطع اتصال"
              destructive
              onConfirm={async () => onChanged(await api.disconnectTelegram(botId))}
            />
          </>
        ) : (
          <form onSubmit={connect} noValidate className="flex flex-col gap-4">
            <ol className="list-[persian] space-y-1.5 ps-5 text-sm leading-7">
              <li>
                در تلگرام با <span dir="ltr">@BotFather</span> گفتگو را شروع کنید.
              </li>
              <li>
                دستور <span dir="ltr">/newbot</span> را بفرستید و نام و نام کاربری ربات را انتخاب کنید.
              </li>
              <li>توکنی که BotFather می‌فرستد را کپی کنید و در کادر زیر بچسبانید.</li>
            </ol>
            <div className="grid gap-1.5">
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
                aria-describedby={error ? "tg-token-error" : undefined}
              />
            </div>
            {error && (
              <ErrorNote>
                <span id="tg-token-error">{error}</span>
              </ErrorNote>
            )}
            <div>
              <Button type="submit" disabled={busy}>
                {busy ? "در حال اتصال…" : "اتصال"}
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
