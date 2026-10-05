import type { Api } from "@/lib/api";
import { mockLogin, mockLogout, mockMe, mockSignup } from "@/lib/mock/auth";
import * as engine from "@/lib/mock/engine";
import * as tabs from "@/lib/mock/tabs";

/** Small latency so loading states are real. */
const LATENCY_MS = 120;

async function call<T>(fn: () => T): Promise<T> {
  await engine.sleep(LATENCY_MS);
  return fn();
}

/** Mock implementation of the API client. Agent runs, bots and the workspace tabs are backed by fixtures. */
export const mockApi: Api = {
  me: () => call(() => mockMe()),
  login: (email) => call(() => mockLogin(email)),
  signup: (email, password) => call(() => mockSignup(email, password)),
  logout: () => call(() => mockLogout()),

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

  listRevisions: (botId) => call(() => tabs.listRevisions(botId)),
  getRevision: (revisionId) => call(() => tabs.getRevision(revisionId)),
  activateRevision: (revisionId) => call(() => tabs.activateRevision(revisionId)),
  runRevisionTests: (revisionId) => call(() => tabs.runRevisionTests(revisionId)),

  simulatorEvent: (botId, body) => call(() => tabs.simulatorEvent(botId, body)),
  simulatorReset: (botId, revisionId) => call(() => tabs.simulatorReset(botId, revisionId)),

  getDataOverview: (botId) => call(() => tabs.getDataOverview(botId)),
  listRecords: (botId, collection, page) => call(() => tabs.listRecords(botId, collection, page)),
  createRecord: (botId, collection, data) => call(() => tabs.createRecord(botId, collection, data)),
  updateRecord: (botId, collection, recordId, data) =>
    call(() => tabs.updateRecord(botId, collection, recordId, data)),
  deleteRecord: (botId, collection, recordId) => call(() => tabs.deleteRecord(botId, collection, recordId)),
  runRecordAction: (botId, collection, recordId, action) =>
    call(() => tabs.runRecordAction(botId, collection, recordId, action)),

  getTelegram: (botId) => call(() => tabs.getTelegram(botId)),
  connectTelegram: (botId, token) => call(() => tabs.connectTelegram(botId, token)),
  disconnectTelegram: (botId) => call(() => tabs.disconnectTelegram(botId)),
};
