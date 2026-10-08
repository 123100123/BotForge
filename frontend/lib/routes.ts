/**
 * The Business Control Center route map (D03): every section of a business has a URL under /bots/[id].
 * `sectionHref` is the one place that turns a section name into a path; components navigate with
 * `useOpenSection()` (components/app/shell/use-open-section.ts), never with local tab state.
 */

/** Sections with their own route. */
export type SectionName =
  | "overview"
  | "changes"
  | "versions"
  | "capabilities"
  | "operations"
  | "orders"
  | "events"
  | "bookings"
  | "requests"
  | "records"
  | "announcements"
  | "reports"
  | "schedules"
  | "spreadsheets"
  | "test"
  | "settings"
  | "telegram"
  | "team"
  | "groups"
  | "account";

/**
 * Names used by section components written before the routes existed. They map as follows:
 * copilot and agent → changes, data → the first Operations route, simulator → test.
 */
export type LegacySectionName = "copilot" | "agent" | "data" | "simulator";

export type SectionTarget = SectionName | LegacySectionName;

export interface SectionHrefOptions {
  /** For "records": one collection key (`/records/[key]`); omitted, `/records` lists every collection. */
  collection?: string;
  /** For "operations" and "data": the first Operations item of this business (from the nav adapter). */
  operationsHref?: string | null;
}

export function botHref(botId: string): string {
  return `/bots/${encodeURIComponent(botId)}`;
}

export function sectionHref(botId: string, section: SectionTarget, opts: SectionHrefOptions = {}): string {
  const base = botHref(botId);
  switch (section) {
    case "overview":
      return base;
    case "changes":
    case "copilot":
    case "agent":
      return `${base}/changes`;
    case "versions":
      return `${base}/changes/versions`;
    case "capabilities":
      return `${base}/capabilities`;
    case "operations":
    case "data":
      return opts.operationsHref ?? `${base}/records`;
    case "orders":
      return `${base}/orders`;
    case "events":
      return `${base}/events`;
    case "bookings":
      return `${base}/bookings`;
    case "requests":
      return `${base}/requests`;
    case "records":
      return opts.collection ? `${base}/records/${encodeURIComponent(opts.collection)}` : `${base}/records`;
    case "announcements":
      return `${base}/announcements`;
    case "reports":
      return `${base}/reports`;
    case "schedules":
      return `${base}/reports/schedules`;
    case "spreadsheets":
      return `${base}/spreadsheets`;
    case "test":
    case "simulator":
      return `${base}/test`;
    case "settings":
    case "telegram":
      return `${base}/settings/telegram`;
    case "team":
      return `${base}/settings/team`;
    case "groups":
      return `${base}/settings/groups`;
    case "account":
      return `${base}/settings/account`;
  }
}

/** localStorage key of the business opened last (written by the bot layout, read by /bots). */
export const LAST_BOT_KEY = "botforge.lastBot";

export function readLastBot(): string | null {
  try {
    return window.localStorage.getItem(LAST_BOT_KEY);
  } catch {
    return null;
  }
}

export function writeLastBot(botId: string): void {
  try {
    window.localStorage.setItem(LAST_BOT_KEY, botId);
  } catch {
    /* storage unavailable (private mode): the redirect simply falls back to the list */
  }
}
