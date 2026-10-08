"use client";

import { useEffect, useState } from "react";
import { Link2Off, Lock, RefreshCw } from "lucide-react";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { ErrorNote } from "@/components/app/state-blocks";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/errors";
import { fa, formatDate } from "@/lib/format";
import type { TeamMemberOut, TeamOut, TeamRole } from "@/lib/types";
import { CopyButton, DANGER_OUTLINE, LinkBox, PanelSection, SettingsPanel } from "./settings-panel";

const ROLE_LABELS: Record<TeamRole, string> = { customer: "مشتری", staff: "همکار", manager: "مدیر" };
const ROLES: TeamRole[] = ["customer", "staff", "manager"];

/** Display name of a member; the Telegram id is secondary text, never the headline. */
function memberName(m: TeamMemberOut): string {
  return m.display_name?.trim() || "کاربر بدون نام";
}

/** The staff invite link, the head count per role, and the members with their role. */
export function TeamSection({ botId }: { botId: string }) {
  const [team, setTeam] = useState<TeamOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"rotate" | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [savingRole, setSavingRole] = useState<string | null>(null);
  // The team list does not mark the owner; the API refuses to change the owner's role, and that row is locked from then on.
  const [locked, setLocked] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    api.getTeam(botId).then(
      (t) => !cancelled && setTeam(t),
      (err) => !cancelled && setError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [botId]);

  async function rotate() {
    setBusy("rotate");
    setError(null);
    try {
      const link = await api.rotateStaffLink(botId);
      setTeam((t) => (t ? { ...t, ...link } : t));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  // Throws on failure: the confirm dialog shows the message inline and stays open.
  async function revoke() {
    setError(null);
    const link = await api.revokeStaffLink(botId);
    setTeam((t) => (t ? { ...t, ...link } : t));
  }

  async function changeRole(member: TeamMemberOut, role: TeamRole) {
    if (role === member.role) return;
    setSavingRole(member.actor_id);
    setError(null);
    try {
      const saved = await api.setMemberRole(botId, member.actor_id, { role });
      // Refetch so the counts stay right; fall back to patching the row when that fails.
      const next = await api.getTeam(botId).catch(() => null);
      setTeam((t) => next ?? (t ? { ...t, members: t.members.map((m) => (m.actor_id === saved.actor_id ? saved : m)) } : t));
    } catch (err) {
      if (err instanceof ApiError && err.code === "owner_role_locked") {
        setLocked((s) => new Set(s).add(member.actor_id));
      }
      setError(errorMessage(err));
    } finally {
      setSavingRole(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {error && <ErrorNote>{error}</ErrorNote>}
      {!team ? (
        !error && (
          <div role="status" aria-label="در حال بارگذاری" className="flex flex-col gap-3">
            <Skeleton className="h-44 rounded-md" />
            <Skeleton className="h-56 rounded-md" />
          </div>
        )
      ) : (
        <>
          <SettingsPanel
            title="پیوند دعوت همکار"
            description="هر کسی این پیوند را در تلگرام باز کند، همکار ربات می‌شود؛ پس آن را فقط برای افراد مورد اعتماد بفرستید."
            status={
              team.staff_link ? (
                <StatusBadge tone="success" marker>
                  فعال
                </StatusBadge>
              ) : (
                <StatusBadge tone="neutral" marker>
                  بدون پیوند فعال
                </StatusBadge>
              )
            }
          >
            {team.staff_link ? (
              <>
                <PanelSection>
                  <LinkBox value={team.staff_link} />
                  <div className="flex flex-wrap gap-2">
                    <CopyButton value={team.staff_link} variant="primary" />
                    <Button variant="secondary" onClick={() => void rotate()} loading={busy === "rotate"} disabled={busy !== null}>
                      <RefreshCw strokeWidth={1.75} />
                      ساخت پیوند تازه
                    </Button>
                  </div>
                  <p className="max-w-prose text-small text-fg-muted">
                    با ساختن پیوند تازه، پیوند قبلی از کار می‌افتد. همکارانی که قبلاً وصل شده‌اند همکار می‌مانند.
                  </p>
                </PanelSection>
                <PanelSection
                  tone="danger"
                  title="لغو پیوند"
                  description="پیوند فعلی از کار می‌افتد و تا ساختن پیوند تازه، کسی با آن همکار نمی‌شود."
                >
                  <div>
                    <Button variant="secondary" className={DANGER_OUTLINE} onClick={() => setConfirmRevoke(true)} disabled={busy !== null}>
                      <Link2Off strokeWidth={1.75} />
                      لغو پیوند
                    </Button>
                  </div>
                </PanelSection>
              </>
            ) : (
              <PanelSection>
                <p className="text-small text-fg-secondary">الان پیوند دعوتی فعال نیست. برای دعوت همکار، یک پیوند بسازید.</p>
                <div>
                  <Button onClick={() => void rotate()} loading={busy === "rotate"} disabled={busy !== null}>
                    <RefreshCw strokeWidth={1.75} />
                    ساخت پیوند دعوت
                  </Button>
                </div>
              </PanelSection>
            )}
          </SettingsPanel>

          <SettingsPanel
            title="اعضای تیم"
            description="نقش هر عضو را همین‌جا تعیین کنید. اگر نقش کسی را به «مشتری» برگردانید از این فهرست بیرون می‌رود."
          >
            <PanelSection>
              <ul aria-label="تعداد اعضا به تفکیک نقش" className="flex flex-wrap gap-x-6 gap-y-2">
                {ROLES.map((r) => (
                  <li key={r} className="flex items-baseline gap-2 text-small text-fg-secondary">
                    <span>{ROLE_LABELS[r]}</span>
                    <span className="text-metric-sm text-fg">{fa(team.counts[r] ?? 0)}</span>
                  </li>
                ))}
              </ul>
            </PanelSection>
            {team.members.length === 0 ? (
              <PanelSection>
                <p className="text-small text-fg-secondary">
                  هنوز عضوی ثبت نشده است. پس از اینکه کسی ربات را در تلگرام شروع کند، اینجا نمایش داده می‌شود.
                </p>
              </PanelSection>
            ) : (
              <table className="w-full border-t border-border text-small">
                <caption className="sr-only">اعضای تیم و نقش آن‌ها</caption>
                <thead className="bg-surface-sunken text-fg-muted">
                  <tr>
                    <th scope="col" className="px-5 py-2 text-start font-medium">
                      عضو
                    </th>
                    <th scope="col" className="hidden px-3 py-2 text-start font-medium md:table-cell">
                      شروع همکاری
                    </th>
                    <th scope="col" className="px-5 py-2 text-start font-medium">
                      نقش
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {team.members.map((m) => {
                    const name = memberName(m);
                    const isLocked = locked.has(m.actor_id);
                    return (
                      <tr key={m.actor_id} className="border-t border-border">
                        <td className="min-w-0 px-5 py-3">
                          <div className="text-body text-fg">{name}</div>
                          {!m.display_name?.trim() && (
                            <div className="text-caption text-fg-muted">
                              <span dir="ltr" className="inline-block">
                                {m.actor_id}
                              </span>
                            </div>
                          )}
                        </td>
                        <td className="hidden px-3 py-3 text-fg-secondary md:table-cell">{formatDate(m.first_seen)}</td>
                        <td className="px-5 py-3">
                          {isLocked ? (
                            <StatusBadge tone="brand" icon={<Lock strokeWidth={1.75} aria-hidden />}>
                              مالک (مدیر)
                            </StatusBadge>
                          ) : (
                            <Select
                              aria-label={`نقش ${name}`}
                              className="h-9 w-28"
                              value={m.role}
                              disabled={savingRole === m.actor_id}
                              onChange={(e) => void changeRole(m, e.target.value as TeamRole)}
                            >
                              {ROLES.map((r) => (
                                <option key={r} value={r}>
                                  {ROLE_LABELS[r]}
                                </option>
                              ))}
                            </Select>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            <p className="border-t border-border p-5 text-small text-fg-muted">
              مالک ربات همیشه مدیر است و نقش او قابل تغییر نیست.
            </p>
          </SettingsPanel>
        </>
      )}
      <ConfirmDialog
        open={confirmRevoke}
        onOpenChange={setConfirmRevoke}
        title="لغو پیوند دعوت همکار؟"
        description="پیوند فعلی از کار می‌افتد و تا ساختن پیوند تازه، کسی با آن همکار نمی‌شود. همکارانی که قبلاً وصل شده‌اند همکار می‌مانند."
        confirmLabel="لغو پیوند"
        destructive
        onConfirm={revoke}
      />
    </div>
  );
}
