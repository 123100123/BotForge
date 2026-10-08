import { API_BASE_URL, AUTH_PROVIDER, IS_MOCK } from "@/lib/config";
import { ApiError, parseFieldErrors } from "@/lib/errors";
import { mockApi } from "@/lib/mock/api";
import { handleUnauthorized } from "@/lib/session-expiry";
import { getAccessToken } from "@/lib/supabase";
import type {
  AgentRun,
  AnalysisProfileCreateIn,
  AnalysisProfileOut,
  AnalysisProfileUpdateIn,
  AnalysisRunIn,
  AnalysisRunOut,
  AnnouncementIn,
  AnnouncementOut,
  Bot,
  CapabilityConfigIn,
  CapabilityListOut,
  CapabilityOut,
  CapabilityReportOut,
  CapabilityToggleIn,
  CapabilityToggleOut,
  CopilotMessageIn,
  CopilotMessageOut,
  DataActionResult,
  DataOverview,
  DataRecord,
  GroupOut,
  Me,
  MemberRoleIn,
  OverviewOut,
  Period,
  PublishIn,
  PublishOut,
  RecordsPage,
  RevisionDetail,
  RevisionSummary,
  RuntimeResponse,
  ScheduleOut,
  SchedulesIn,
  SimulatorEventBody,
  SimulatorResetResult,
  StaffLinkOut,
  TeamMemberOut,
  TeamOut,
  TelegramStatus,
  TestReport,
  UploadOut,
} from "@/lib/types";

export { ApiError } from "@/lib/errors";
export { UNAUTHORIZED_EVENT } from "@/lib/session-expiry";
export type { SimulatorEventBody } from "@/lib/types";

/** Typed client for the roadmap's "Backend API" table. The mock implements the same interface. */
export interface Api {
  // Auth (own login, NEXT_PUBLIC_AUTH_PROVIDER=local): the session is an HttpOnly cookie set by the
  // backend; the frontend never sees a token. With Supabase sign-in these are not used (lib/auth.tsx).
  /** The signed-in user. Rejects with an ApiError of status 401 when there is no session. */
  me(): Promise<Me>;
  login(email: string, password: string): Promise<Me>;
  signup(email: string, password: string): Promise<Me>;
  logout(): Promise<void>;
  // Bots
  listBots(): Promise<Bot[]>;
  createBot(name: string): Promise<Bot>;
  getBot(botId: string): Promise<Bot>;
  updateBot(botId: string, patch: { name: string }): Promise<Bot>;
  deleteBot(botId: string): Promise<void>;
  // Agent runs (events are read with streamRunEvents in lib/sse.ts)
  createRun(botId: string, message: string): Promise<AgentRun>;
  listRuns(botId: string): Promise<AgentRun[]>;
  getRun(runId: string): Promise<AgentRun>;
  postRunMessage(runId: string, message: string): Promise<AgentRun>;
  approveRun(runId: string): Promise<AgentRun>;
  rejectRun(runId: string): Promise<AgentRun>;
  /** A new run from the original request of a failed or interrupted run (409 for any other status). */
  retryRun(runId: string): Promise<AgentRun>;
  // Revisions and tests
  listRevisions(botId: string): Promise<RevisionSummary[]>;
  getRevision(revisionId: string): Promise<RevisionDetail>;
  activateRevision(revisionId: string): Promise<RevisionSummary>;
  runRevisionTests(revisionId: string): Promise<TestReport>;
  // Simulator
  simulatorEvent(botId: string, body: SimulatorEventBody): Promise<RuntimeResponse>;
  simulatorReset(botId: string, revisionId: string | null): Promise<SimulatorResetResult>;
  // Data admin (live data of the ACTIVE revision; bodies are `{"data": {...}}`)
  getDataOverview(botId: string): Promise<DataOverview>;
  /** Newest first. */
  listRecords(botId: string, collection: string, page?: { limit?: number; offset?: number }): Promise<RecordsPage>;
  createRecord(botId: string, collection: string, data: Record<string, unknown>): Promise<DataRecord>;
  updateRecord(
    botId: string,
    collection: string,
    recordId: number,
    data: Record<string, unknown>,
  ): Promise<DataRecord>;
  deleteRecord(botId: string, collection: string, recordId: number): Promise<void>;
  /** `action`: "cancel" on a booking record, an owner-action key on a request record. */
  runRecordAction(
    botId: string,
    collection: string,
    recordId: number,
    action: string,
  ): Promise<DataActionResult>;
  // Telegram
  getTelegram(botId: string): Promise<TelegramStatus>;
  connectTelegram(botId: string, token: string): Promise<TelegramStatus>;
  disconnectTelegram(botId: string): Promise<TelegramStatus>;
  /** Owner: clear a POLLING_CONFLICT park so the server polls Telegram again; returns the new status. */
  retryTelegram(botId: string): Promise<TelegramStatus>;
  // Capability Center
  listCapabilities(botId: string): Promise<CapabilityListOut>;
  /** `dry_run: true` returns the plan without creating a revision. */
  enableCapability(botId: string, capId: string, body: CapabilityToggleIn): Promise<CapabilityToggleOut>;
  disableCapability(botId: string, capId: string, body: CapabilityToggleIn): Promise<CapabilityToggleOut>;
  updateCapabilityConfig(botId: string, capId: string, body: CapabilityConfigIn): Promise<CapabilityOut>;
  // Reports
  getOverview(botId: string, period: Period): Promise<OverviewOut>;
  getCapabilityReport(botId: string, capKey: string, period: Period): Promise<CapabilityReportOut>;
  // Spreadsheet intelligence (Data Analyst)
  uploadWorkbook(botId: string, file: File): Promise<UploadOut>;
  listUploads(botId: string): Promise<UploadOut[]>;
  listAnalysisProfiles(botId: string): Promise<AnalysisProfileOut[]>;
  createAnalysisProfile(botId: string, body: AnalysisProfileCreateIn): Promise<AnalysisProfileOut>;
  updateAnalysisProfile(botId: string, profileId: string, body: AnalysisProfileUpdateIn): Promise<AnalysisProfileOut>;
  runAnalysis(botId: string, profileId: string, body: AnalysisRunIn): Promise<AnalysisRunOut>;
  listAnalysisRuns(botId: string, profileId?: string): Promise<AnalysisRunOut[]>;
  // Copilot (ask mode)
  copilotMessage(botId: string, body: CopilotMessageIn): Promise<CopilotMessageOut>;
  // Team, groups, announcements, schedules
  getTeam(botId: string): Promise<TeamOut>;
  rotateStaffLink(botId: string): Promise<StaffLinkOut>;
  revokeStaffLink(botId: string): Promise<StaffLinkOut>;
  setMemberRole(botId: string, actorId: string, body: MemberRoleIn): Promise<TeamMemberOut>;
  listGroups(botId: string): Promise<GroupOut[]>;
  publishToGroup(botId: string, chatId: number, body: PublishIn): Promise<PublishOut>;
  createAnnouncement(botId: string, body: AnnouncementIn): Promise<AnnouncementOut>;
  listAnnouncements(botId: string): Promise<AnnouncementOut[]>;
  getSchedules(botId: string): Promise<ScheduleOut[]>;
  putSchedules(botId: string, body: SchedulesIn): Promise<ScheduleOut[]>;
}

const STATUS_MESSAGES: Record<number, string> = {
  401: "نشست شما منقضی شده است؛ دوباره وارد شوید.",
  403: "به این بخش دسترسی ندارید.",
  404: "مورد درخواستی پیدا نشد.",
  409: "این کار در وضعیت فعلی ممکن نیست.",
  422: "اطلاعات واردشده معتبر نیست.",
  429: "درخواست‌ها زیاد بود؛ کمی بعد دوباره امتحان کنید.",
};

/** CSRF header the backend requires on every non-GET/HEAD request, including login and signup. */
const CSRF_HEADERS = { "X-BotForge-CSRF": "1" } as const;

/**
 * How a call to the backend authenticates (JSON requests, the upload, the agent event stream):
 * - local: the HttpOnly session cookie, which the browser sends by itself ("same-origin"), and the CSRF
 *   header on every method other than GET and HEAD.
 * - supabase: the Supabase access token as `Authorization: Bearer` (supabase-js refreshes it before it
 *   expires) and no cookies at all ("omit"), so no ambient credential ever reaches the API. The CSRF
 *   header is sent the same way; the backend does not need it there.
 */
export async function authInit(
  method: string,
): Promise<{ credentials: RequestCredentials; headers: Record<string, string> }> {
  const csrf: Record<string, string> = method === "GET" || method === "HEAD" ? {} : { ...CSRF_HEADERS };
  if (AUTH_PROVIDER !== "supabase") return { credentials: "same-origin", headers: csrf };
  const token = await getAccessToken();
  return { credentials: "omit", headers: token ? { ...csrf, Authorization: `Bearer ${token}` } : csrf };
}

/** Parses the backend's `{"error": {"code", "message"}}` envelope into an ApiError. */
export async function parseErrorResponse(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string; details?: unknown; field_errors?: unknown } };
    if (body?.error?.message) {
      return new ApiError(
        body.error.code ?? "error",
        body.error.message,
        res.status,
        body.error.details,
        parseFieldErrors(body.error),
      );
    }
  } catch {
    /* body was not JSON */
  }
  return new ApiError(
    "http_" + res.status,
    STATUS_MESSAGES[res.status] ?? "خطایی در سرور رخ داد. دوباره امتحان کنید.",
    res.status,
  );
}

interface RequestOptions {
  /**
   * The own login's session probe (`GET /me` from the AuthProvider): its 401 only means "signed out", so
   * it never triggers the sign-out redirect.
   */
  probe?: boolean;
}

async function request<T>(method: string, path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  let res: Response;
  try {
    const auth = await authInit(method);
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      credentials: auth.credentials,
      headers: {
        ...auth.headers,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("network_error", "ارتباط با سرور برقرار نشد. اینترنت خود را بررسی کنید.");
  }
  if (!res.ok) {
    const err = await parseErrorResponse(res);
    // The session expired or was revoked: sign out (Supabase) and go to /login?next=<this page>.
    // The caller still gets the error.
    if (res.status === 401 && !path.startsWith("/auth/") && !options.probe) void handleUnauthorized();
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * Raw-body upload (no multipart): the file is the request body and its name travels in the query string.
 * It authenticates like every other call (`authInit`), so with the own login the PUT carries the CSRF header.
 */
async function uploadFile(botId: string, file: File): Promise<UploadOut> {
  let res: Response;
  try {
    const auth = await authInit("PUT");
    res = await fetch(
      `${API_BASE_URL}/uploads/bots/${encodeURIComponent(botId)}?filename=${encodeURIComponent(file.name)}`,
      {
        method: "PUT",
        credentials: auth.credentials,
        headers: {
          ...auth.headers,
          "Content-Type": file.type || "application/octet-stream",
        },
        body: file,
      },
    );
  } catch {
    throw new ApiError("network_error", "ارتباط با سرور برقرار نشد. اینترنت خود را بررسی کنید.");
  }
  if (!res.ok) {
    const err = await parseErrorResponse(res);
    if (res.status === 401) void handleUnauthorized();
    throw err;
  }
  return (await res.json()) as UploadOut;
}

const enc = encodeURIComponent;

export const realApi: Api = {
  me: () => request("GET", "/me", undefined, { probe: true }),
  login: async (email, password) => (await request<{ user: Me }>("POST", "/auth/login", { email, password })).user,
  signup: async (email, password) => (await request<{ user: Me }>("POST", "/auth/signup", { email, password })).user,
  logout: () => request("POST", "/auth/logout"),

  listBots: () => request("GET", "/bots"),
  createBot: (name) => request("POST", "/bots", { name }),
  getBot: (botId) => request("GET", `/bots/${enc(botId)}`),
  updateBot: (botId, patch) => request("PATCH", `/bots/${enc(botId)}`, patch),
  deleteBot: (botId) => request("DELETE", `/bots/${enc(botId)}`),

  createRun: (botId, message) => request("POST", `/bots/${enc(botId)}/runs`, { message }),
  listRuns: (botId) => request("GET", `/bots/${enc(botId)}/runs`),
  getRun: (runId) => request("GET", `/runs/${enc(runId)}`),
  postRunMessage: (runId, message) => request("POST", `/runs/${enc(runId)}/messages`, { message }),
  approveRun: (runId) => request("POST", `/runs/${enc(runId)}/approve`),
  rejectRun: (runId) => request("POST", `/runs/${enc(runId)}/reject`),
  retryRun: (runId) => request("POST", `/runs/${enc(runId)}/retry`),

  listRevisions: (botId) => request("GET", `/bots/${enc(botId)}/revisions`),
  getRevision: (revisionId) => request("GET", `/revisions/${enc(revisionId)}`),
  activateRevision: (revisionId) => request("POST", `/revisions/${enc(revisionId)}/activate`),
  runRevisionTests: (revisionId) => request("POST", `/revisions/${enc(revisionId)}/tests/run`),

  simulatorEvent: (botId, body) => request("POST", `/bots/${enc(botId)}/simulator/events`, body),
  simulatorReset: (botId, revisionId) =>
    request("POST", `/bots/${enc(botId)}/simulator/reset`, { revision_id: revisionId }),

  getDataOverview: (botId) => request("GET", `/bots/${enc(botId)}/data`),
  listRecords: (botId, collection, page) => {
    const q = new URLSearchParams();
    if (page?.limit !== undefined) q.set("limit", String(page.limit));
    if (page?.offset !== undefined) q.set("offset", String(page.offset));
    const qs = q.toString();
    return request("GET", `/bots/${enc(botId)}/data/${enc(collection)}${qs ? `?${qs}` : ""}`);
  },
  createRecord: (botId, collection, data) =>
    request("POST", `/bots/${enc(botId)}/data/${enc(collection)}`, { data }),
  updateRecord: (botId, collection, recordId, data) =>
    request("PATCH", `/bots/${enc(botId)}/data/${enc(collection)}/${recordId}`, { data }),
  deleteRecord: (botId, collection, recordId) =>
    request("DELETE", `/bots/${enc(botId)}/data/${enc(collection)}/${recordId}`),
  runRecordAction: (botId, collection, recordId, action) =>
    request("POST", `/bots/${enc(botId)}/data/${enc(collection)}/${recordId}/actions/${enc(action)}`),

  getTelegram: (botId) => request("GET", `/bots/${enc(botId)}/telegram`),
  connectTelegram: (botId, token) => request("POST", `/bots/${enc(botId)}/telegram/connect`, { token }),
  retryTelegram: (botId) => request("POST", `/bots/${enc(botId)}/telegram/retry`),
  disconnectTelegram: async (botId) =>
    (await request<TelegramStatus | undefined>("DELETE", `/bots/${enc(botId)}/telegram`)) ??
    (await request<TelegramStatus>("GET", `/bots/${enc(botId)}/telegram`)),

  listCapabilities: (botId) => request("GET", `/bots/${enc(botId)}/capabilities`),
  enableCapability: (botId, capId, body) =>
    request("POST", `/bots/${enc(botId)}/capabilities/${enc(capId)}/enable`, body),
  disableCapability: (botId, capId, body) =>
    request("POST", `/bots/${enc(botId)}/capabilities/${enc(capId)}/disable`, body),
  updateCapabilityConfig: (botId, capId, body) =>
    request("PATCH", `/bots/${enc(botId)}/capabilities/${enc(capId)}/config`, body),

  getOverview: (botId, period) => request("GET", `/bots/${enc(botId)}/reports/overview?period=${enc(period)}`),
  getCapabilityReport: (botId, capKey, period) =>
    request("GET", `/bots/${enc(botId)}/reports/${enc(capKey)}?period=${enc(period)}`),

  uploadWorkbook: (botId, file) => uploadFile(botId, file),
  listUploads: (botId) => request("GET", `/bots/${enc(botId)}/uploads`),
  listAnalysisProfiles: (botId) => request("GET", `/bots/${enc(botId)}/analysis/profiles`),
  createAnalysisProfile: (botId, body) => request("POST", `/bots/${enc(botId)}/analysis/profiles`, body),
  updateAnalysisProfile: (botId, profileId, body) =>
    request("PATCH", `/bots/${enc(botId)}/analysis/profiles/${enc(profileId)}`, body),
  runAnalysis: (botId, profileId, body) =>
    request("POST", `/bots/${enc(botId)}/analysis/profiles/${enc(profileId)}/run`, body),
  listAnalysisRuns: (botId, profileId) =>
    request("GET", `/bots/${enc(botId)}/analysis/runs${profileId ? `?profile_id=${enc(profileId)}` : ""}`),

  copilotMessage: (botId, body) => request("POST", `/bots/${enc(botId)}/copilot/messages`, body),

  getTeam: (botId) => request("GET", `/bots/${enc(botId)}/team`),
  rotateStaffLink: (botId) => request("POST", `/bots/${enc(botId)}/team/staff-link`),
  revokeStaffLink: async (botId) =>
    (await request<StaffLinkOut | undefined>("DELETE", `/bots/${enc(botId)}/team/staff-link`)) ?? {
      staff_link: null,
      staff_link_code: null,
    },
  setMemberRole: (botId, actorId, body) =>
    request("PATCH", `/bots/${enc(botId)}/team/members/${enc(actorId)}`, body),

  listGroups: (botId) => request("GET", `/bots/${enc(botId)}/groups`),
  publishToGroup: (botId, chatId, body) => request("POST", `/bots/${enc(botId)}/groups/${chatId}/publish`, body),
  createAnnouncement: (botId, body) => request("POST", `/bots/${enc(botId)}/announcements`, body),
  listAnnouncements: (botId) => request("GET", `/bots/${enc(botId)}/announcements`),
  getSchedules: (botId) => request("GET", `/bots/${enc(botId)}/schedules`),
  putSchedules: (botId, body) => request("PUT", `/bots/${enc(botId)}/schedules`, body),
};

/** The client the app uses: fixtures in mock mode, the real backend otherwise. */
export const api: Api = IS_MOCK ? mockApi : realApi;
