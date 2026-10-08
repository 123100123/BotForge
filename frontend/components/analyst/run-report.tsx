"use client";

import { CircleCheckIcon, MinusIcon, PlusIcon, RefreshCwIcon, TriangleAlertIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { ErrorNote } from "@/components/app/state-blocks";
import { ReportMetrics } from "@/components/reports/metric-view";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { errorMessage } from "@/lib/errors";
import { fa, formatDateTime, formatNumber } from "@/lib/format";
import type { AnalysisAnomaly, AnalysisProfileOut, AnalysisRunOut } from "@/lib/types";
import { AssistantLimit, isDailyCap } from "./assistant-limit";
import { ProfileBuilder } from "./profile-builder";
import { SEVERITY_ICONS, SEVERITY_LABELS, SEVERITY_TONE, STATUS_ICONS, STATUS_LABELS, STATUS_TONE, submitterText } from "./labels";

export function RunStatusBadge({ status }: { status: AnalysisRunOut["status"] }) {
  const Icon = STATUS_ICONS[status];
  return (
    <StatusBadge tone={STATUS_TONE[status]} icon={<Icon aria-hidden strokeWidth={1.75} />}>
      {STATUS_LABELS[status]}
    </StatusBadge>
  );
}

function Panel({ title, children, id }: { title: ReactNode; children: ReactNode; id: string }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 rounded-md border border-border bg-surface p-5">
      <h3 id={id} className="text-h3 text-fg">
        {title}
      </h3>
      {children}
    </section>
  );
}

function AnomalyRow({ a }: { a: AnalysisAnomaly }) {
  const Icon = SEVERITY_ICONS[a.severity];
  const comparison = [a.value !== null && `مقدار ${formatNumber(a.value)}`, a.expected !== null && `در برابر انتظار ${formatNumber(a.expected)}`].filter(Boolean).join(" ");
  return (
    <li className="flex flex-col gap-2 border-t border-border py-3 first:border-t-0 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:gap-4">
      <StatusBadge tone={SEVERITY_TONE[a.severity]} icon={<Icon aria-hidden strokeWidth={1.75} />} className="mt-0.5 self-start sm:w-20 sm:justify-center">
        {SEVERITY_LABELS[a.severity]}
      </StatusBadge>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-body font-medium text-fg">{a.label}</span>
        <span className="text-small text-fg-secondary">
          ستون <bdi>{a.field}</bdi>
          {a.group && (
            <>
              {" · "}
              <bdi>{a.group}</bdi>
            </>
          )}
        </span>
        {comparison && <span className="text-small text-fg-secondary tabular-nums">{comparison}</span>}
      </div>
    </li>
  );
}

function ColumnDiff({ title, names, kind }: { title: string; names: string[]; kind: "missing" | "new" }) {
  const Icon = kind === "missing" ? MinusIcon : PlusIcon;
  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-small font-semibold text-fg">{title}</h4>
      {names.length === 0 ? (
        <p className="text-small text-fg-muted">موردی نیست.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {names.map((n) => (
            <li key={n} className={`flex items-center gap-2 text-small font-medium ${kind === "missing" ? "text-danger-text" : "text-success-text"}`}>
              <Icon aria-hidden className="size-4 shrink-0" strokeWidth={2} />
              <span className="sr-only">{kind === "missing" ? "ستون گمشده:" : "ستون تازه:"}</span>
              <bdi>{n}</bdi>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type Intent = "update" | "new";

/** The file's columns no longer match the profile: say so plainly, list what changed, offer the two fixes. */
function SchemaMismatch({
  botId,
  run,
  profile,
  onProfileCreated,
}: {
  botId: string;
  run: AnalysisRunOut;
  profile: AnalysisProfileOut | null;
  onProfileCreated: (profile: AnalysisProfileOut, intent: Intent) => void;
}) {
  const [intent, setIntent] = useState<Intent | null>(null);
  const name = profile?.name ?? "تحلیل";
  return (
    <section aria-labelledby="mismatch-title" className="flex flex-col gap-5 rounded-md border border-border bg-surface p-5">
      <div className="flex items-start gap-3">
        <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-sm bg-warning-soft text-warning-text">
          <TriangleAlertIcon className="size-5" strokeWidth={1.75} />
        </span>
        <div className="flex flex-col gap-1">
          <h3 id="mismatch-title" className="text-h3 text-fg">
            ساختار این فایل با پروفایل «{name}» فرق دارد
          </h3>
          <p className="text-small text-fg-secondary">
            ستون‌های فایل با ستون‌هایی که پروفایل انتظار دارد یکی نیست، برای همین تحلیل اجرا نشد و هیچ عددی از این فایل حساب نشد. این کار برای این است که نتیجهٔ اشتباه نگیرید. اگر ساختار تازه
            درست است، پروفایل را برای آن به‌روز کنید.
          </p>
        </div>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <ColumnDiff title="ستون‌هایی که در فایل نیستند" names={run.schema_diff?.missing ?? []} kind="missing" />
        <ColumnDiff title="ستون‌های تازه در فایل" names={run.schema_diff?.new ?? []} kind="new" />
      </div>
      {run.upload_id ? (
        <div className="flex flex-col gap-4 border-t border-border pt-5">
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant={intent === "update" ? "secondary" : "primary"} onClick={() => setIntent("update")} aria-expanded={intent === "update"}>
              به‌روزرسانی پروفایل
            </Button>
            <Button type="button" variant="secondary" onClick={() => setIntent("new")} aria-expanded={intent === "new"}>
              ساخت پروفایل تازه
            </Button>
          </div>
          {intent === "update" && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-fg-secondary">دستیار از ساختار تازهٔ این فایل یک نسخهٔ به‌روز از «{name}» می‌سازد؛ بعد می‌توانید آن را ویرایش کنید. پروفایل فعلی دست‌نخورده می‌ماند.</p>
              <ProfileBuilder
                key="update"
                botId={botId}
                uploadId={run.upload_id}
                initialName={`${name} (به‌روز)`}
                daily={profile?.daily_report ?? false}
                submitLabel="ساخت نسخهٔ به‌روز با دستیار"
                onCreated={(p) => onProfileCreated(p, "update")}
              />
            </div>
          )}
          {intent === "new" && (
            <div className="flex flex-col gap-3">
              <p className="text-small text-fg-secondary">یک پروفایل جدا برای همین ساختار ساخته می‌شود و «{name}» برای فایل‌های قدیمی می‌ماند.</p>
              <ProfileBuilder key="new" botId={botId} uploadId={run.upload_id} onCreated={(p) => onProfileCreated(p, "new")} />
            </div>
          )}
        </div>
      ) : (
        <p className="border-t border-border pt-4 text-small text-fg-muted">فایل این اجرا دیگر در دسترس نیست؛ برای ادامه فایل را دوباره بارگذاری کنید.</p>
      )}
    </section>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-caption text-fg-muted">{label}</dt>
      <dd className="text-small text-fg">{children}</dd>
    </div>
  );
}

/**
 * One analysis run: who sent which file when, then its result. ok: metric strip, rankings, notable findings and
 * the assistant's summary. schema_changed: what differs and how to fix it. failed: the cause and a retry.
 */
export function RunReport({
  botId,
  run,
  profile,
  onProfileCreated,
  onRetry,
}: {
  botId: string;
  run: AnalysisRunOut;
  profile: AnalysisProfileOut | null;
  onProfileCreated: (profile: AnalysisProfileOut, intent: Intent) => void;
  /** Runs the same profile on the same file again; throws to show the error here. */
  onRetry: (run: AnalysisRunOut) => Promise<void>;
}) {
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<{ message: string; cap: boolean } | null>(null);
  const anomalies = run.anomalies ?? [];
  const metrics = run.metrics ?? [];

  async function retry() {
    setRetrying(true);
    setRetryError(null);
    try {
      await onRetry(run);
    } catch (err) {
      setRetryError({ message: errorMessage(err), cap: isDailyCap(err) });
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-4 rounded-md border border-border bg-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-h2 text-fg">نتیجهٔ تحلیل</h2>
          <RunStatusBadge status={run.status} />
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 lg:grid-cols-4">
          <Meta label="فایل">{run.filename ? <bdi dir="ltr">{run.filename}</bdi> : "فایل حذف‌شده"}</Meta>
          <Meta label="پروفایل">{profile?.name ?? "پروفایل حذف‌شده"}</Meta>
          <Meta label="ارسال‌کننده">{submitterText(run.submitted_by)}</Meta>
          <Meta label="زمان">{formatDateTime(run.created_at)}</Meta>
        </dl>
      </header>

      {run.status === "ok" && (
        <>
          {metrics.length === 0 ? (
            <p className="text-small text-fg-muted">این اجرا شاخصی نداشت.</p>
          ) : (
            <ReportMetrics metrics={metrics} period={null} breakdownAs="table" />
          )}

          <Panel id="anomalies-title" title={<>موارد قابل توجه{anomalies.length > 0 && <span className="ms-1.5 font-normal text-fg-muted">({fa(anomalies.length)})</span>}</>}>
            {anomalies.length === 0 ? (
              <p className="flex items-center gap-2 text-small text-fg-secondary">
                <CircleCheckIcon aria-hidden className="size-4 text-success-text" strokeWidth={1.75} />
                در این فایل موردی که با بررسی‌های پروفایل بخواند پیدا نشد.
              </p>
            ) : (
              <ul>
                {anomalies.map((a, i) => (
                  <AnomalyRow key={`${a.check_id}-${i}`} a={a} />
                ))}
              </ul>
            )}
          </Panel>

          {run.narrative ? (
            <figure className="flex flex-col gap-2 rounded-md border border-border bg-surface p-5">
              <figcaption className="text-caption font-medium text-fg-muted">خلاصهٔ دستیار</figcaption>
              <blockquote className="border-s-2 border-brand ps-4 text-body text-fg">{run.narrative}</blockquote>
            </figure>
          ) : (
            <p className="text-caption text-fg-muted">برای این اجرا خلاصهٔ دستیار نوشته نشد.</p>
          )}
        </>
      )}

      {run.status === "schema_changed" && <SchemaMismatch botId={botId} run={run} profile={profile} onProfileCreated={onProfileCreated} />}

      {run.status === "failed" && (
        <section aria-labelledby="failed-title" className="flex flex-col gap-3 rounded-md border border-border bg-surface p-5">
          <h3 id="failed-title" className="text-h3 text-fg">
            تحلیل این فایل انجام نشد
          </h3>
          <p className="text-small text-fg-secondary">{run.error || "در خواندن یا تحلیل فایل خطایی رخ داد."}</p>
          {retryError && (retryError.cap ? <AssistantLimit /> : <ErrorNote>{retryError.message}</ErrorNote>)}
          {run.upload_id && profile ? (
            <Button type="button" variant="secondary" size="sm" className="w-fit" loading={retrying} onClick={() => void retry()}>
              <RefreshCwIcon aria-hidden />
              تلاش دوباره
            </Button>
          ) : (
            <p className="text-small text-fg-muted">فایل یا پروفایل این اجرا دیگر در دسترس نیست؛ فایل را دوباره بارگذاری کنید.</p>
          )}
        </section>
      )}
    </div>
  );
}
