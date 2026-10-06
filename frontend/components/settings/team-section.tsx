"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy, Link2Off, Lock, RefreshCw, Users } from "lucide-react";
import { ErrorNote } from "@/components/app/state-blocks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { ApiError, errorMessage } from "@/lib/errors";
import { fa } from "@/lib/format";
import type { TeamMemberOut, TeamOut, TeamRole } from "@/lib/types";
import { ConfirmDialog } from "./confirm-dialog";

const ROLE_LABELS: Record<TeamRole, string> = { customer: "مشتری", staff: "همکار", manager: "مدیر" };
const ROLES: TeamRole[] = ["customer", "staff", "manager"];

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** The staff invite link, the head count per role, and the members with their role. */
export function TeamSection({ botId }: { botId: string }) {
  const [team, setTeam] = useState<TeamOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"rotate" | "revoke" | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  const [savingRole, setSavingRole] = useState<string | null>(null);
  // The team list does not mark the owner; the API refuses to change the owner's role, and that row is locked from then on.
  const [locked, setLocked] = useState<Set<string>>(new Set());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function rotate() {
    setBusy("rotate");
    setError(null);
    try {
      const link = await api.rotateStaffLink(botId);
      setTeam((t) => (t ? { ...t, ...link } : t));
      setCopied(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function revoke() {
    setBusy("revoke");
    setError(null);
    try {
      const link = await api.revokeStaffLink(botId);
      setTeam((t) => (t ? { ...t, ...link } : t));
      setCopied(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
      setConfirmRevoke(false);
    }
  }

  async function copy() {
    if (!team?.staff_link) return;
    setCopied((await copyText(team.staff_link)) ? "yes" : "no");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(null), 2500);
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Users className="size-5 text-muted-foreground" />
          تیم
        </CardTitle>
        <CardDescription>همکاران و مدیران را با یک پیوند دعوت کنید و نقش هر عضو را همین‌جا تعیین کنید.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {error && <ErrorNote>{error}</ErrorNote>}
        {!team ? (
          !error && <div role="status" aria-label="در حال بارگذاری" className="h-24 animate-pulse rounded-xl bg-muted" />
        ) : (
          <>
            <div className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold">پیوند دعوت همکار</h3>
              {team.staff_link ? (
                <>
                  <div className="rounded-md border bg-muted/40 p-3 text-sm break-all" dir="ltr">
                    {team.staff_link}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={copy}>
                      {copied === "yes" ? <Check /> : <Copy />}
                      {copied === "yes" ? "کپی شد" : "کپی پیوند"}
                    </Button>
                    <Button variant="outline" onClick={rotate} disabled={busy !== null}>
                      <RefreshCw className={busy === "rotate" ? "animate-spin" : undefined} />
                      ساخت/تعویض لینک
                    </Button>
                    <Button variant="ghost" className="text-destructive" onClick={() => setConfirmRevoke(true)} disabled={busy !== null}>
                      <Link2Off />
                      لغو لینک
                    </Button>
                  </div>
                  {copied === "no" && (
                    <p role="status" className="text-sm text-destructive">
                      کپی خودکار انجام نشد؛ پیوند را دستی انتخاب و کپی کنید.
                    </p>
                  )}
                </>
              ) : (
                <>
                  <p className="text-sm leading-7 text-muted-foreground">الان پیوند دعوتی فعال نیست.</p>
                  <div>
                    <Button onClick={rotate} disabled={busy !== null}>
                      <RefreshCw className={busy === "rotate" ? "animate-spin" : undefined} />
                      ساخت/تعویض لینک
                    </Button>
                  </div>
                </>
              )}
              <p className="text-sm leading-7 text-muted-foreground">
                هر کسی این پیوند را در تلگرام باز کند، همکار ربات می‌شود؛ پس آن را فقط برای افراد مورد اعتماد بفرستید. با تعویض یا لغو
                پیوند، پیوند قبلی از کار می‌افتد و همکارانی که قبلاً وصل شده‌اند همکار می‌مانند.
              </p>
            </div>

            <div role="group" aria-label="تعداد اعضا به تفکیک نقش" className="flex flex-wrap gap-2">
              {ROLES.map((r) => (
                <Badge key={r} variant="outline">
                  {ROLE_LABELS[r]}: {fa(team.counts[r] ?? 0)}
                </Badge>
              ))}
            </div>

            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">اعضا</h3>
              {team.members.length === 0 ? (
                <p className="text-sm leading-7 text-muted-foreground">
                  هنوز عضوی ثبت نشده است. پس از اینکه کسی ربات را در تلگرام شروع کند، اینجا نمایش داده می‌شود.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full min-w-[30rem] text-sm">
                    <thead className="bg-muted/50 text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 text-start font-medium">نام</th>
                        <th className="px-3 py-2 text-start font-medium">شناسه</th>
                        <th className="px-3 py-2 text-start font-medium">نقش</th>
                      </tr>
                    </thead>
                    <tbody>
                      {team.members.map((m) => {
                        const label = m.display_name ?? m.actor_id;
                        const isLocked = locked.has(m.actor_id);
                        return (
                          <tr key={m.actor_id} className="border-t">
                            <td className="px-3 py-2">{m.display_name ?? "بدون نام"}</td>
                            <td className="px-3 py-2 text-muted-foreground">
                              <span dir="ltr" className="inline-block">
                                {m.actor_id}
                              </span>
                            </td>
                            <td className="px-3 py-2">
                              {isLocked ? (
                                <Badge variant="accent">
                                  <Lock />
                                  مالک (مدیر)
                                </Badge>
                              ) : (
                                <Select
                                  aria-label={`نقش ${label}`}
                                  className="h-8 w-28"
                                  value={m.role}
                                  disabled={savingRole === m.actor_id}
                                  onChange={(e) => changeRole(m, e.target.value as TeamRole)}
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
                </div>
              )}
              <p className="text-sm leading-7 text-muted-foreground">
                مالک ربات همیشه مدیر است و نقش او قابل تغییر نیست. این فهرست همکاران و مدیران را نشان می‌دهد؛ اگر نقش کسی را به «مشتری» برگردانید از فهرست بیرون می‌رود.
              </p>
            </div>
          </>
        )}
      </CardContent>
      <ConfirmDialog
        open={confirmRevoke}
        title="لغو پیوند دعوت همکار؟"
        description="پیوند فعلی از کار می‌افتد و تا ساختن پیوند تازه، کسی با آن همکار نمی‌شود. همکارانی که قبلاً وصل شده‌اند همکار می‌مانند."
        confirmLabel="لغو پیوند"
        destructive
        busy={busy === "revoke"}
        onConfirm={revoke}
        onCancel={() => setConfirmRevoke(false)}
      />
    </Card>
  );
}
