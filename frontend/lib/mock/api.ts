import type { Api } from "@/lib/api";
import * as analyst from "@/lib/mock/analyst";
import * as capabilities from "@/lib/mock/capabilities";
import * as copilot from "@/lib/mock/copilot";
import * as engine from "@/lib/mock/engine";
import * as reports from "@/lib/mock/reports";
import * as tabs from "@/lib/mock/tabs";
import * as team from "@/lib/mock/team";

/** Small latency so loading states are real. */
const LATENCY_MS = 120;

async function call<T>(fn: () => T): Promise<T> {
  await engine.sleep(LATENCY_MS);
  return fn();
}

/** Mock implementation of the API client. Agent runs, bots and the workspace tabs are backed by fixtures. */
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

  listCapabilities: () => call(() => capabilities.listCapabilities()),
  enableCapability: (_botId, capId, body) => call(() => capabilities.enableCapability(capId, body)),
  disableCapability: (_botId, capId, body) => call(() => capabilities.disableCapability(capId, body)),
  updateCapabilityConfig: (_botId, capId, body) => call(() => capabilities.updateCapabilityConfig(capId, body)),

  getOverview: (_botId, period) => call(() => reports.getOverview(period)),
  getCapabilityReport: (_botId, capKey, period) => call(() => reports.getCapabilityReport(capKey, period)),

  uploadWorkbook: (_botId, file) => call(() => analyst.uploadWorkbook(file)),
  listUploads: () => call(() => analyst.listUploads()),
  listAnalysisProfiles: () => call(() => analyst.listAnalysisProfiles()),
  createAnalysisProfile: (_botId, body) => call(() => analyst.createAnalysisProfile(body)),
  updateAnalysisProfile: (_botId, profileId, body) => call(() => analyst.updateAnalysisProfile(profileId, body)),
  runAnalysis: (_botId, profileId, body) => call(() => analyst.runAnalysis(profileId, body)),
  listAnalysisRuns: (_botId, profileId) => call(() => analyst.listAnalysisRuns(profileId)),

  copilotMessage: (_botId, body) => call(() => copilot.copilotMessage(body)),

  getTeam: () => call(() => team.getTeam()),
  rotateStaffLink: () => call(() => team.rotateStaffLink()),
  revokeStaffLink: () => call(() => team.revokeStaffLink()),
  setMemberRole: (_botId, actorId, body) => call(() => team.setMemberRole(actorId, body)),
  listGroups: () => call(() => team.listGroups()),
  publishToGroup: () => call(() => team.publishToGroup()),
  createAnnouncement: (_botId, body) => call(() => team.createAnnouncement(body)),
  listAnnouncements: () => call(() => team.listAnnouncements()),
  getSchedules: () => call(() => team.getSchedules()),
  putSchedules: (_botId, body) => call(() => team.putSchedules(body)),
};
