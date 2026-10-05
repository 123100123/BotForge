import type {
  AnnouncementIn,
  AnnouncementOut,
  GroupOut,
  MemberRoleIn,
  PublishOut,
  ScheduleOut,
  SchedulesIn,
  StaffLinkOut,
  TeamMemberOut,
  TeamOut,
} from "@/lib/types";
import { ApiError } from "@/lib/errors";

/** Demo team, staff link, groups, announcements and schedules (state lives for the browser session). */

let staffCode: string | null = "demo1234";
let members: TeamMemberOut[] = [
  { actor_id: "tg:1001", display_name: "مریم احمدی", role: "manager", first_seen: new Date(Date.now() - 10 * 86_400_000).toISOString() },
  { actor_id: "tg:1002", display_name: "رضا کریمی", role: "staff", first_seen: new Date(Date.now() - 4 * 86_400_000).toISOString() },
];
let announcements: AnnouncementOut[] = [];
let schedules: ScheduleOut[] = [
  { id: "mock-schedule-1", kind: "daily_summary", time: "20:00", weekday: null, enabled: true, metrics: ["bookings", "orders"] },
  { id: "mock-schedule-2", kind: "weekly_summary", time: "09:00", weekday: 6, enabled: false, metrics: ["revenue"] },
];

const GROUPS: GroupOut[] = [
  { chat_id: -1001234567890, title: "گروه مشتریان (نمونه)", kind: "supergroup", added_at: new Date(Date.now() - 6 * 86_400_000).toISOString(), active: true },
];

function link(): StaffLinkOut {
  return {
    staff_link: staffCode ? `https://t.me/demo_bot?start=staff_${staffCode}` : null,
    staff_link_code: staffCode,
  };
}

export function getTeam(): TeamOut {
  const counts: Record<string, number> = { customer: 41 };
  for (const m of members) counts[m.role] = (counts[m.role] ?? 0) + 1;
  return { ...link(), members: members.map((m) => ({ ...m })), counts };
}

export function rotateStaffLink(): StaffLinkOut {
  staffCode = Math.random().toString(36).slice(2, 10);
  return link();
}

export function revokeStaffLink(): StaffLinkOut {
  staffCode = null;
  return link();
}

export function setMemberRole(actorId: string, body: MemberRoleIn): TeamMemberOut {
  const m = members.find((x) => x.actor_id === actorId);
  if (!m) throw new ApiError("not_found", "عضو پیدا نشد.", 404);
  members = members.map((x) => (x === m ? { ...x, role: body.role } : x));
  return { ...m, role: body.role };
}

export function listGroups(): GroupOut[] {
  return GROUPS;
}

export function publishToGroup(): PublishOut {
  return { queued: true, message: "در صف ارسال قرار گرفت." };
}

export function createAnnouncement(body: AnnouncementIn): AnnouncementOut {
  const out: AnnouncementOut = {
    id: `mock-announcement-${announcements.length + 1}`,
    text: body.text,
    audience: body.audience,
    recipients: body.audience === "managers" ? 1 : body.audience === "staff" ? 2 : 41,
    created_at: new Date().toISOString(),
    status: "queued",
  };
  announcements = [out, ...announcements];
  return out;
}

export function listAnnouncements(): AnnouncementOut[] {
  return announcements;
}

export function getSchedules(): ScheduleOut[] {
  return schedules;
}

export function putSchedules(body: SchedulesIn): ScheduleOut[] {
  schedules = body.schedules;
  return schedules;
}
