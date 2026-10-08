import type { ReactNode } from "react";
import { CircleCheck, CircleDashed, CircleX } from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";
import { fa } from "@/lib/format";
import { Disclosure } from "./disclosure";

export interface TestFailure {
  id: string;
  title: string;
  message: string;
}

export interface TestGroupView {
  label: string;
  count: number;
  items?: { title: string; reason?: string }[];
}

interface TestSummaryProps {
  /** null while no suite has run yet. */
  total: number | null;
  passed: number;
  failed: number;
  failures?: TestFailure[];
  /** For example «۹ آزمون از روی پیکربندی و ۳ آزمون از روی خواستهٔ شما ساخته شد». */
  note?: string | null;
  /** Extra remarks of the assistant about how the tests were written. */
  notes?: string[];
  /** Carried over / new / set aside, for a change to an existing bot. */
  groups?: TestGroupView[];
  /** Earlier attempts, oldest first (one sentence each). */
  attempts?: string[];
  /** The scenario list, shown when the owner expands «فهرست آزمون‌ها». Omit when it is not available. */
  children?: ReactNode;
  /** Size of the scenario list behind the expander, when it differs from `total`. */
  listCount?: number;
  /** Shown instead of the numbers while the suite has not run. */
  pendingText?: string;
}

/** «۲۱ از ۲۱ آزمون موفق» with a status badge, failures listed, and the scenarios expandable. Pure: props only. */
export function TestSummary({
  total,
  passed,
  failed,
  failures = [],
  note,
  notes = [],
  groups = [],
  attempts = [],
  children,
  pendingText = "آزمون‌ها بعد از ساخت اجرا می‌شوند.",
  listCount,
}: TestSummaryProps) {
  const ran = total !== null;
  const allPassed = ran && failed === 0;
  const Icon = !ran ? CircleDashed : allPassed ? CircleCheck : CircleX;
  const shownGroups = groups.filter((g) => g.count > 0);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Icon
          strokeWidth={1.75}
          aria-hidden
          className={`size-5 shrink-0 ${!ran ? "text-fg-muted" : allPassed ? "text-success-text" : "text-danger-text"}`}
        />
        {ran ? (
          <p className="text-h3 text-fg">
            {fa(passed)} از {fa(total)} آزمون موفق
          </p>
        ) : (
          <p className="text-body text-fg-secondary">{pendingText}</p>
        )}
        {ran && (
          <StatusBadge
            tone={allPassed ? "success" : "danger"}
            icon={allPassed ? <CircleCheck strokeWidth={1.75} aria-hidden /> : <CircleX strokeWidth={1.75} aria-hidden />}
          >
            {allPassed ? "همه موفق" : `${fa(failed)} ناموفق`}
          </StatusBadge>
        )}
      </div>

      {note && <p className="text-small text-fg-secondary">{note}</p>}

      {notes.length > 0 && (
        <ul aria-label="نکته‌های ساخت آزمون" className="flex flex-col gap-1 rounded-sm bg-surface-sunken p-3 text-small text-fg-secondary">
          {notes.map((n, i) => (
            <li key={i} className="whitespace-pre-line">
              {n}
            </li>
          ))}
        </ul>
      )}

      {failures.length > 0 && (
        <ul className="flex flex-col gap-2">
          {failures.map((f) => (
            <li key={f.id} className="rounded-sm bg-danger-soft p-3 text-body">
              <div className="font-medium text-danger-text">{f.title}</div>
              <div className="text-small text-fg-secondary">{f.message}</div>
            </li>
          ))}
        </ul>
      )}

      {shownGroups.length > 0 && (
        <ul className="flex flex-col gap-1.5 text-small text-fg-secondary">
          {shownGroups.map((g) => (
            <li key={g.label}>
              <span className="font-medium text-fg">
                {fa(g.count)} {g.label}
              </span>
              {g.items && g.items.length > 0 && (
                <ul className="mt-1 flex flex-col gap-1 ps-4">
                  {g.items.map((item, i) => (
                    <li key={i}>
                      {item.title}
                      {item.reason && <span className="block text-caption text-fg-muted">{item.reason}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      {children && (
        <Disclosure title="فهرست آزمون‌ها" as="h4" meta={listCount !== undefined ? `${fa(listCount)} مورد` : ran ? `${fa(total)} مورد` : undefined}>
          {children}
        </Disclosure>
      )}

      {attempts.length > 0 && (
        <div className="text-caption text-fg-muted">
          <div className="font-medium">تلاش‌های قبلی</div>
          <ul>
            {attempts.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
