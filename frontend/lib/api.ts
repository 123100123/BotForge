import { API_BASE_URL, IS_MOCK } from "@/lib/config";
import { ApiError, parseFieldErrors } from "@/lib/errors";
import { mockApi } from "@/lib/mock/api";
import type {
  AgentRun,
  Bot,
  DataActionResult,
  DataOverview,
  DataRecord,
  Me,
  RecordsPage,
  RevisionDetail,
  RevisionSummary,
  RuntimeResponse,
  SimulatorEventBody,
  SimulatorResetResult,
  TelegramStatus,
  TestReport,
} from "@/lib/types";

export { ApiError } from "@/lib/errors";
export type { SimulatorEventBody } from "@/lib/types";

/** Typed client for the roadmap's "Backend API" table. The mock implements the same interface. */
export interface Api {
  // Auth: the session is an HttpOnly cookie set by the backend; the frontend never sees a token.
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
}

const STATUS_MESSAGES: Record<number, string> = {
  401: "نشست شما منقضی شده است؛ دوباره وارد شوید.",
  403: "به این بخش دسترسی ندارید.",
  404: "مورد درخواستی پیدا نشد.",
  409: "این کار در وضعیت فعلی ممکن نیست.",
  422: "اطلاعات واردشده معتبر نیست.",
  429: "درخواست‌ها زیاد بود؛ کمی بعد دوباره امتحان کنید.",
};

/**
 * Window event fired when a request outside /auth gets a 401 (the session expired or was revoked).
 * The AuthProvider listens and drops to the signed-out state, which sends the user to /login.
 */
export const UNAUTHORIZED_EVENT = "botforge:unauthorized";

/** CSRF header the backend requires on every non-GET/HEAD request, including login and signup. */
const CSRF_HEADERS = { "X-BotForge-CSRF": "1" } as const;

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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    const safe = method === "GET" || method === "HEAD";
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        ...(safe ? {} : CSRF_HEADERS),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("network_error", "ارتباط با سرور برقرار نشد. اینترنت خود را بررسی کنید.");
  }
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw await parseErrorResponse(res);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const realApi: Api = {
  me: () => request("GET", "/me"),
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
  disconnectTelegram: async (botId) =>
    (await request<TelegramStatus | undefined>("DELETE", `/bots/${enc(botId)}/telegram`)) ??
    (await request<TelegramStatus>("GET", `/bots/${enc(botId)}/telegram`)),
};

/** The client the app uses: fixtures in mock mode, the real backend otherwise. */
export const api: Api = IS_MOCK ? mockApi : realApi;
