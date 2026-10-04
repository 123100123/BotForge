/**
 * In-browser stand-in for the backend agent: plays the recorded fixture runs as an event stream
 * that follows the real event contract (envelope + payloads from lib/types.ts). State is kept in
 * localStorage so a page reload does not lose bots, runs or events; a run that was mid-play
 * resumes from where it stopped.
 */
import { ApiError } from "@/lib/errors";
import { initialMockBots, initialMockRevisions } from "@/lib/fixtures/bots";
import { createRunScript } from "@/lib/fixtures/create-run";
import { modifyRunScript } from "@/lib/fixtures/modify-run";
import type { ScriptContext, ScriptItem } from "@/lib/fixtures/types";
import type {
  AgentEvent,
  AgentEventType,
  AgentRun,
  Bot,
  EventPayloads,
  RevisionSummary,
  RunKind,
} from "@/lib/types";

interface RunMeta {
  revisionId: string;
  revisionNumber: number;
  /** Index of the next script item to play (the item a paused run waits on, while paused). */
  cursor: number;
}

interface StoredRun extends AgentRun {
  meta: RunMeta;
}

interface MockDb {
  bots: Bot[];
  revisions: RevisionSummary[];
  runs: StoredRun[];
  events: Record<string, AgentEvent[]>;
  seq: number;
}

const STORAGE_KEY = "botforge.mock.db.v1";

let db: MockDb | null = null;
const playing = new Set<string>();
const listeners = new Map<string, Set<(e: AgentEvent) => void>>();

export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function persist() {
  if (!db) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(db));
  } catch {
    /* storage unavailable: state lives for this page load only */
  }
}

function freshDb(): MockDb {
  return { bots: initialMockBots(), revisions: initialMockRevisions(), runs: [], events: {}, seq: 0 };
}

export function getDb(): MockDb {
  if (db) return db;
  let loaded: MockDb | null = null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) loaded = JSON.parse(raw) as MockDb;
  } catch {
    loaded = null;
  }
  db = loaded ?? freshDb();
  // Runs that were playing when the page went away continue from their cursor.
  for (const run of db.runs) {
    if (run.status === "running") setTimeout(() => void advance(run.id), 0);
  }
  return db;
}

function newId(prefix: string): string {
  const d = getDb();
  d.seq += 1;
  return `${prefix}_${Date.now().toString(36)}${d.seq}`;
}

function publicRun(run: StoredRun): AgentRun {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { meta, ...rest } = run;
  return { ...rest };
}

function buildScript(run: StoredRun): ScriptItem[] {
  const ctx: ScriptContext = { revisionId: run.meta.revisionId, revisionNumber: run.meta.revisionNumber };
  return run.kind === "create" ? createRunScript(ctx) : modifyRunScript(ctx);
}

function findRun(runId: string): StoredRun {
  const run = getDb().runs.find((r) => r.id === runId);
  if (!run) throw new ApiError("not_found", "اجرای مورد نظر پیدا نشد.", 404);
  return run;
}

function touch(run: StoredRun) {
  run.updated_at = new Date().toISOString();
  persist();
}

function emit<T extends AgentEventType>(run: StoredRun, type: T, payload: EventPayloads[T]): AgentEvent {
  const d = getDb();
  const list = (d.events[run.id] ??= []);
  const event = {
    id: list.length + 1,
    run_id: run.id,
    ts: new Date().toISOString(),
    type,
    payload,
  } as AgentEvent;
  list.push(event);

  if (event.type === "phase_started") run.phase = event.payload.phase;
  if (event.type === "usage") run.usage = event.payload;
  if (event.type === "error") run.status = "failed";
  if (event.type === "deployed") applyDeployed(run, event.payload.revision_id, event.payload.number);

  touch(run);
  listeners.get(run.id)?.forEach((fn) => fn(event));
  return event;
}

function applyDeployed(run: StoredRun, revisionId: string, number: number) {
  const d = getDb();
  const now = new Date().toISOString();
  for (const rev of d.revisions) {
    if (rev.bot_id === run.bot_id && rev.status === "active") rev.status = "superseded";
  }
  const first = (d.events[run.id] ?? []).find((e) => e.type === "owner_message");
  d.revisions.push({
    id: revisionId,
    bot_id: run.bot_id,
    number,
    parent_id: run.base_revision_id,
    status: "active",
    change_request: first && first.type === "owner_message" ? first.payload.text : null,
    created_at: now,
    activated_at: now,
    tests_total: 12,
    tests_passed: 12,
  });
  const bot = d.bots.find((b) => b.id === run.bot_id);
  if (bot) {
    bot.status = "live";
    bot.active_revision_id = revisionId;
    bot.active_revision_number = number;
  }
  run.result_revision_id = revisionId;
}

/** Plays script items until the run pauses at a gate, finishes, or is no longer running. */
async function advance(runId: string): Promise<void> {
  if (playing.has(runId)) return;
  playing.add(runId);
  try {
    for (;;) {
      const run = getDb().runs.find((r) => r.id === runId);
      if (!run || run.status !== "running") return;
      const item = buildScript(run)[run.meta.cursor];
      if (!item) {
        run.status = "done";
        touch(run);
        return;
      }
      if ("wait" in item) {
        run.status = item.wait === "message" ? "waiting_user" : "waiting_approval";
        touch(run);
        return;
      }
      await sleep(item.delay);
      if (run.status !== "running") return;
      run.meta.cursor += 1;
      emit(run, item.event.type, item.event.payload as never);
    }
  } finally {
    playing.delete(runId);
  }
}

function resume(run: StoredRun) {
  run.meta.cursor += 1; // step over the gate
  run.status = "running";
  touch(run);
  void advance(run.id);
}

/* ------------------------------------------------------------------ public engine API */

export function listBots(): Bot[] {
  return getDb().bots.map((b) => ({ ...b }));
}

export function getBot(botId: string): Bot {
  const bot = getDb().bots.find((b) => b.id === botId);
  if (!bot) throw new ApiError("not_found", "ربات مورد نظر پیدا نشد.", 404);
  return { ...bot };
}

export function createBot(name: string): Bot {
  const bot: Bot = {
    id: newId("bot"),
    name,
    status: "draft",
    active_revision_id: null,
    active_revision_number: null,
    tg_username: null,
    created_at: new Date().toISOString(),
  };
  getDb().bots.unshift(bot);
  persist();
  return { ...bot };
}

export function renameBot(botId: string, name: string): Bot {
  const bot = getDb().bots.find((b) => b.id === botId);
  if (!bot) throw new ApiError("not_found", "ربات مورد نظر پیدا نشد.", 404);
  bot.name = name;
  persist();
  return { ...bot };
}

export function deleteBot(botId: string) {
  const d = getDb();
  d.bots = d.bots.filter((b) => b.id !== botId);
  d.runs = d.runs.filter((r) => r.bot_id !== botId);
  d.revisions = d.revisions.filter((r) => r.bot_id !== botId);
  persist();
}

export function listRevisions(botId: string): RevisionSummary[] {
  return getDb()
    .revisions.filter((r) => r.bot_id === botId)
    .sort((a, b) => b.number - a.number)
    .map((r) => ({ ...r }));
}

export function listRuns(botId: string): AgentRun[] {
  return getDb()
    .runs.filter((r) => r.bot_id === botId)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map(publicRun);
}

export function getRun(runId: string): AgentRun {
  return publicRun(findRun(runId));
}

export function createRun(botId: string, message: string): AgentRun {
  const d = getDb();
  const bot = d.bots.find((b) => b.id === botId);
  if (!bot) throw new ApiError("not_found", "ربات مورد نظر پیدا نشد.", 404);
  const open = d.runs.find((r) => r.bot_id === botId && (r.status === "running" || r.status === "waiting_user" || r.status === "waiting_approval"));
  if (open) throw new ApiError("run_active", "برای این ربات یک اجرای فعال وجود دارد.", 409);

  const kind: RunKind = bot.active_revision_id ? "modify" : "create";
  const id = newId("run");
  const now = new Date().toISOString();
  const maxNumber = d.revisions.filter((r) => r.bot_id === botId).reduce((m, r) => Math.max(m, r.number), 0);
  const run: StoredRun = {
    id,
    bot_id: botId,
    kind,
    phase: "understand",
    status: "running",
    base_revision_id: bot.active_revision_id,
    result_revision_id: null,
    usage: null,
    created_at: now,
    updated_at: now,
    meta: { revisionId: `rev_${id}`, revisionNumber: maxNumber + 1, cursor: 0 },
  };
  d.runs.push(run);
  d.events[id] = [];
  emit(run, "owner_message", { text: message });
  void advance(id);
  return publicRun(run);
}

export function postRunMessage(runId: string, message: string): AgentRun {
  const run = findRun(runId);
  if (run.status === "waiting_user") {
    emit(run, "owner_message", { text: message });
    resume(run);
  } else if (run.status === "waiting_approval") {
    emit(run, "owner_message", { text: message });
    emit(run, "agent_message", {
      text: "در حالت نمایشی، تغییر پیش‌نویس در این مرحله شبیه‌سازی نمی‌شود. برای ادامه، پیش‌نویس را تأیید یا رد کنید.",
    });
  } else {
    throw new ApiError("run_not_waiting", "این اجرا در حال حاضر پیامی نمی‌پذیرد.", 409);
  }
  return publicRun(run);
}

export function approveRun(runId: string): AgentRun {
  const run = findRun(runId);
  if (run.status !== "waiting_approval") {
    throw new ApiError("run_not_waiting", "این اجرا منتظر تأیید نیست.", 409);
  }
  const request = [...(getDb().events[runId] ?? [])].reverse().find((e) => e.type === "approval_requested");
  if (request && request.type === "approval_requested" && !request.payload.can_approve) {
    throw new ApiError("approval_blocked", request.payload.blocked_reason || "تأیید این نسخه ممکن نیست.", 409);
  }
  resume(run);
  return publicRun(run);
}

export function rejectRun(runId: string): AgentRun {
  const run = findRun(runId);
  if (run.status !== "waiting_approval") {
    throw new ApiError("run_not_waiting", "این اجرا منتظر تأیید نیست.", 409);
  }
  emit(run, "phase_finished", { phase: "await_approval", ok: false, summary: "پیش‌نویس رد شد" });
  emit(run, "agent_message", { text: "پیش‌نویس کنار گذاشته شد و ربات فعلی بدون تغییر ماند." });
  run.status = "rejected";
  touch(run);
  return publicRun(run);
}

/** Events with id greater than `afterId`, oldest first. */
export function eventsAfter(runId: string, afterId: number): AgentEvent[] {
  return (getDb().events[runId] ?? []).filter((e) => e.id > afterId);
}

export function subscribe(runId: string, fn: (e: AgentEvent) => void): () => void {
  let set = listeners.get(runId);
  if (!set) {
    set = new Set();
    listeners.set(runId, set);
  }
  set.add(fn);
  return () => {
    set.delete(fn);
  };
}
