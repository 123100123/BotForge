import type { Api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import * as engine from "@/lib/mock/engine";

/** Small latency so loading states are real. */
const LATENCY_MS = 120;

async function call<T>(fn: () => T): Promise<T> {
  await engine.sleep(LATENCY_MS);
  return fn();
}

function unavailable(): never {
  throw new ApiError("mock_unavailable", "این بخش در حالت نمایشی در دسترس نیست.", 501);
}

/** Mock implementation of the API client. Only the agent flow and bots are backed by fixtures. */
export const mockApi: Api = {
  me: () => call(() => ({ id: "mock-user", email: "demo@botforge.test" })),

  listBots: () => call(() => engine.listBots()),
  createBot: (name) => call(() => engine.createBot(name)),
  getBot: (botId) => call(() => engine.getBot(botId)),
  updateBot: (botId, patch) => call(() => engine.renameBot(botId, patch.name)),
  deleteBot: (botId) => call(() => engine.deleteBot(botId)),

  createRun: (botId, message) => call(() => engine.createRun(botId, message)),
  listRuns: (botId) => call(() => engine.listRuns(botId)),
  getRun: (runId) => call(() => engine.getRun(runId)),
  postRunMessage: (runId, message) => call(() => engine.postRunMessage(runId, message)),
  approveRun: (runId) => call(() => engine.approveRun(runId)),
  rejectRun: (runId) => call(() => engine.rejectRun(runId)),

  listRevisions: (botId) => call(() => engine.listRevisions(botId)),
  getRevision: () => call(unavailable),
  activateRevision: () => call(unavailable),
  runRevisionTests: () => call(unavailable),

  simulatorEvent: () => call(unavailable),
  simulatorReset: () => call(() => undefined),

  getDataOverview: () => call(() => ({ collections: [] })),
  listRecords: () => call(() => []),
  createRecord: () => call(unavailable),
  updateRecord: () => call(unavailable),
  deleteRecord: () => call(unavailable),
  runRecordAction: () => call(unavailable),

  getTelegram: (botId) =>
    call(() => {
      const bot = engine.getBot(botId);
      return {
        connected: bot.tg_username !== null,
        username: bot.tg_username,
        bot_link: bot.tg_username ? `https://t.me/${bot.tg_username}` : null,
        owner_link: null,
        last_error: null,
      };
    }),
  connectTelegram: () => call(unavailable),
  disconnectTelegram: () => call(unavailable),
};
