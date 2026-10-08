/**
 * Mock implementations of the endpoints behind the Data, Settings, Simulator, Tests and Versions
 * tabs. They follow backend/app/api/data.py and the roadmap's response-shape table, including the
 * error codes and Persian messages the tabs react to.
 */
import { ApiError, ERROR_CODES } from "@/lib/errors";
import { countsOf, detailOf, hasNoStoredTests, specOf, type StoredRevision } from "@/lib/fixtures/revisions";
import { niloofarActorName } from "@/lib/fixtures/records";
import { reportOf } from "@/lib/fixtures/scenarios";
import { capabilitySummaries } from "@/lib/mock/capabilities";
import { getDb, newId, persist } from "@/lib/mock/engine";
import { resetSandbox, simulate } from "@/lib/mock/simulator";
import type {
  BookingCapability,
  BotSpec,
  DataActionResult,
  DataCollection,
  DataOverview,
  DataRecord,
  FieldDef,
  OrdersCapability,
  RecordsPage,
  RequestCapability,
  RevisionDetail,
  RevisionSummary,
  RuntimeResponse,
  SimulatorEventBody,
  SimulatorResetResult,
  TelegramStatus,
  TestReport,
} from "@/lib/types";

/* ------------------------------------------------------------------ revisions */

function summaryOf(rev: StoredRevision): RevisionSummary {
  return {
    id: rev.id,
    number: rev.number,
    status: rev.status,
    change_request: rev.change_request,
    created_at: rev.created_at,
    activated_at: rev.activated_at,
    tests: hasNoStoredTests(rev) ? null : countsOf(rev.variant),
  };
}

function findRevision(revisionId: string): StoredRevision {
  const rev = getDb().revisions.find((r) => r.id === revisionId);
  if (!rev) throw new ApiError("revision_not_found", "نسخه پیدا نشد.", 404);
  return rev;
}

export function listRevisions(botId: string): RevisionSummary[] {
  return getDb()
    .revisions.filter((r) => r.bot_id === botId)
    .sort((a, b) => b.number - a.number)
    .map(summaryOf);
}

export function getRevision(revisionId: string): RevisionDetail {
  return detailOf(findRevision(revisionId));
}

/** Rollback: a superseded revision becomes active again. */
export function activateRevision(revisionId: string): RevisionSummary {
  const d = getDb();
  const rev = findRevision(revisionId);
  if (rev.status === "active") throw new ApiError("revision_already_active", "این نسخه همین حالا فعال است.", 409);
  if (rev.status === "rejected") throw new ApiError("revision_not_activatable", "نسخهٔ ردشده فعال نمی‌شود.", 409);
  if (countsOf(rev.variant).failed > 0) {
    throw new ApiError("tests_failing", "این نسخه آزمون ناموفق دارد و فعال نمی‌شود.", 409);
  }
  for (const r of d.revisions) if (r.bot_id === rev.bot_id && r.status === "active") r.status = "superseded";
  rev.status = "active";
  rev.activated_at = new Date().toISOString();
  const bot = d.bots.find((b) => b.id === rev.bot_id);
  if (bot) {
    bot.active_revision_id = rev.id;
    bot.active_revision_number = rev.number;
  }
  persist();
  return summaryOf(rev);
}

export function runRevisionTests(revisionId: string): TestReport {
  const rev = findRevision(revisionId);
  // A revision stored without scenarios gets them derived from its spec, then stored with the report.
  if (hasNoStoredTests(rev)) {
    rev.ran = true;
    persist();
  }
  return detailOf(rev).test_report ?? reportOf([]);
}

/* ------------------------------------------------------------------ simulator */

function revisionForSimulator(botId: string, revisionId: string | null): StoredRevision {
  const d = getDb();
  const bot = d.bots.find((b) => b.id === botId);
  const id = revisionId ?? bot?.active_revision_id ?? null;
  if (!id) throw new ApiError(ERROR_CODES.noActiveRevision, "این ربات هنوز نسخهٔ فعالی ندارد.", 409);
  const rev = findRevision(id);
  // Same rule as backend/app/simulator/service.py: only a draft or the active revision can be tried.
  if (rev.status !== "draft" && rev.status !== "active") {
    throw new ApiError(ERROR_CODES.revisionNotSimulatable, "فقط پیش‌نویس یا نسخهٔ فعال قابل آزمایش است.", 409);
  }
  return rev;
}

export function simulatorEvent(botId: string, body: SimulatorEventBody): RuntimeResponse {
  return simulate(botId, specOf(revisionForSimulator(botId, body.revision_id)), body);
}

export function simulatorReset(botId: string, revisionId: string | null): SimulatorResetResult {
  const loaded = resetSandbox(botId, specOf(revisionForSimulator(botId, revisionId)));
  return { ok: true, loaded };
}

/* ------------------------------------------------------------------ data admin */

const SYSTEM_COLUMNS = [
  { key: "actor_id", label: "کاربر" },
  { key: "item_id", label: "مورد" },
  { key: "status", label: "وضعیت" },
  { key: "created_at", label: "زمان" },
];

function activeSpec(botId: string): BotSpec {
  const bot = getDb().bots.find((b) => b.id === botId);
  const rev = bot?.active_revision_id ? getDb().revisions.find((r) => r.id === bot.active_revision_id) : undefined;
  if (!rev) throw new ApiError(ERROR_CODES.noActiveRevision, "این ربات هنوز نسخهٔ فعالی ندارد.", 409);
  return specOf(rev);
}

/** The mock specs have no orders capability, so a demo one keeps the orders views exercised. */
const DEMO_ORDERS_KEY = "orders";
const DEMO_ORDERS = {
  key: DEMO_ORDERS_KEY,
  label: "سفارش‌ها",
  checkout_fields: [
    { key: "phone", label: "تلفن", type: "phone", required: true, choices: null, default: null },
    { key: "address", label: "نشانی", type: "long_text", required: false, choices: null, default: null },
  ] as FieldDef[],
  statuses: [
    { key: "placed", label: "ثبت‌شده" },
    { key: "confirmed", label: "تأیید شده" },
    { key: "shipped", label: "ارسال شد" },
    { key: "cancelled", label: "لغو شده" },
  ],
  owner_actions: [
    { key: "confirm", label: "تأیید سفارش", from_statuses: ["placed"], to_status: "confirmed" },
    { key: "ship", label: "ارسال شد", from_statuses: ["confirmed"], to_status: "shipped" },
    { key: "cancel", label: "لغو سفارش", from_statuses: ["placed", "confirmed"], to_status: "cancelled" },
  ],
};

/** The active orders capability, or the demo definition when the spec has none. */
function ordersDef(spec: BotSpec): Pick<OrdersCapability, "key" | "label" | "checkout_fields" | "statuses" | "owner_actions"> & { enabled: boolean } {
  const cap = spec.capabilities.find((c): c is OrdersCapability => c.type === "orders");
  return cap ?? { ...DEMO_ORDERS, enabled: true };
}

function collectionsOf(spec: BotSpec): DataCollection[] {
  const out: DataCollection[] = spec.resources.map((r) => ({
    key: r.key,
    kind: "resource",
    label: r.label,
    label_plural: r.label_plural,
    writable: true,
    fields: r.fields,
    system_columns: [],
    title_field: r.title_field,
    timezone: spec.bot.timezone,
  }));
  for (const cap of spec.capabilities) {
    if (cap.type === "booking") {
      out.push({
        key: cap.key,
        kind: "booking",
        label: cap.title,
        label_plural: cap.title,
        writable: false,
        enabled: cap.enabled,
        fields: cap.form_fields,
        system_columns: SYSTEM_COLUMNS,
        resource: cap.resource,
        timezone: spec.bot.timezone,
        statuses: [
          { key: "confirmed", label: "تأیید شده" },
          { key: "waitlisted", label: "لیست انتظار" },
          { key: "cancelled", label: "لغو شده" },
        ],
        // The admin cancel ignores the cancellation deadline; it applies to active bookings only.
        actions: cap.cancellation.enabled ? [{ key: "cancel", label: "لغو ثبت‌نام", from_statuses: ["confirmed", "waitlisted"] }] : [],
      });
    } else if (cap.type === "request") {
      out.push({
        key: cap.key,
        kind: "request",
        label: cap.title,
        label_plural: cap.title,
        writable: false,
        enabled: cap.enabled,
        fields: cap.form_fields,
        system_columns: SYSTEM_COLUMNS.filter((c) => cap.item_resource !== null || c.key !== "item_id"),
        resource: cap.item_resource,
        timezone: spec.bot.timezone,
        statuses: cap.statuses,
        actions: cap.owner_actions.map((a) => ({ key: a.key, label: a.label, from_statuses: a.from_statuses })),
      });
    }
  }
  const orders = ordersDef(spec);
  out.push({
    key: orders.key,
    kind: "orders",
    label: orders.label,
    label_plural: orders.label,
    writable: false,
    enabled: orders.enabled,
    fields: orders.checkout_fields,
    system_columns: SYSTEM_COLUMNS.filter((c) => c.key !== "item_id"),
    timezone: spec.bot.timezone,
    statuses: orders.statuses,
    actions: orders.owner_actions.map((a) => ({ key: a.key, label: a.label, from_statuses: a.from_statuses })),
  });
  // Mock only: the Capability Center switches «رویدادها» without building a new spec, so the matching
  // collections (an events resource and its registrations) follow the mock capability state.
  if (capabilitySummaries().some((c) => c.id === "events" && c.enabled) && !out.some((c) => c.key === "event")) {
    out.push(
      {
        key: "event",
        kind: "resource",
        label: "رویداد",
        label_plural: "رویدادها",
        writable: true,
        fields: [],
        system_columns: [],
        title_field: "title",
        timezone: spec.bot.timezone,
      },
      {
        key: "event_registration",
        kind: "booking",
        label: "ثبت‌نام رویداد",
        label_plural: "ثبت‌نام‌های رویداد",
        writable: false,
        enabled: true,
        fields: [],
        system_columns: SYSTEM_COLUMNS,
        resource: "event",
        timezone: spec.bot.timezone,
        statuses: [
          { key: "confirmed", label: "تأیید شده" },
          { key: "cancelled", label: "لغو شده" },
        ],
        actions: [],
      },
    );
  }
  return out;
}

export function getDataOverview(botId: string): DataOverview {
  return { collections: collectionsOf(activeSpec(botId)) };
}

function recordsOf(botId: string): DataRecord[] {
  const d = getDb();
  return (d.records[botId] ??= []);
}

/** Two sample orders for the demo orders collection, added once per bot (the fixtures have none). */
function seedDemoOrders(botId: string): void {
  const d = getDb();
  const records = recordsOf(botId);
  if (records.some((r) => r.collection === DEMO_ORDERS_KEY)) return;
  const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
  const samples: { actor: string; status: string; at: string; data: Record<string, unknown> }[] = [
    {
      actor: "5012345701",
      status: "placed",
      at: ago(40 * 60_000),
      data: {
        items: [
          { item_id: 1, title: "فیلتر روغن", qty: 2, unit_price: 250_000 },
          { item_id: 2, title: "لنت ترمز", qty: 1, unit_price: 600_000 },
        ],
        total: 1_100_000,
        payment_status: "unpaid",
        phone: "09121234567",
        address: "تهران، خیابان ولیعصر، پلاک ۱۲",
      },
    },
    {
      actor: "6001001",
      status: "confirmed",
      at: ago(26 * 3_600_000),
      data: {
        items: [{ item_id: 3, title: "شمع موتور", qty: 4, unit_price: 162_500 }],
        total: 650_000,
        payment_status: "paid",
        phone: "09351112233",
        address: "",
      },
    },
    {
      actor: "5012345801",
      status: "placed",
      at: ago(3 * 3_600_000),
      data: {
        items: [
          { item_id: 4, title: "روغن موتور ۴ لیتری", qty: 1, unit_price: 1_450_000 },
          { item_id: 1, title: "فیلتر روغن", qty: 1, unit_price: 250_000 },
          { item_id: 5, title: "فیلتر هوا", qty: 1, unit_price: 320_000 },
          { item_id: 6, title: "برف‌پاک‌کن", qty: 2, unit_price: 180_000 },
        ],
        total: 2_380_000,
        payment_status: "unpaid",
        phone: "09123334455",
        address: "تهران، پاسداران، کوچهٔ بیست و یکم، پلاک ۶",
      },
    },
    {
      actor: "6001003",
      status: "shipped",
      at: ago(3 * 24 * 3_600_000),
      data: {
        items: [{ item_id: 2, title: "لنت ترمز", qty: 2, unit_price: 600_000 }],
        total: 1_200_000,
        payment_status: "unpaid",
        phone: "09361239876",
        address: "کرج، گوهردشت، بلوک ۷",
      },
    },
    {
      actor: "5012345702",
      status: "cancelled",
      at: ago(5 * 24 * 3_600_000),
      data: {
        items: [{ item_id: 3, title: "شمع موتور", qty: 4, unit_price: 162_500 }],
        total: 650_000,
        payment_status: "unpaid",
        phone: "09101110000",
        address: "",
      },
    },
    {
      actor: "6001001",
      status: "placed",
      at: ago(55 * 60_000),
      data: {
        items: [{ item_id: 7, title: "باتری ۶۰ آمپر", qty: 1, unit_price: 3_900_000 }],
        total: 3_900_000,
        payment_status: "unpaid",
        phone: "09121234567",
        address: "تهران، خیابان ولیعصر، پلاک ۱۲",
      },
    },
    {
      actor: "5012345701",
      status: "confirmed",
      at: ago(9 * 3_600_000),
      data: {
        items: [
          { item_id: 8, title: "ضدیخ", qty: 3, unit_price: 210_000 },
          { item_id: 9, title: "شیشه‌شوی", qty: 2, unit_price: 90_000 },
        ],
        total: 810_000,
        payment_status: "unpaid",
        phone: "09121234500",
        address: "تهران، شهرک غرب",
      },
    },
  ];
  for (const sample of samples) {
    d.recordSeq += 1;
    records.push({
      id: d.recordSeq,
      collection: DEMO_ORDERS_KEY,
      data: sample.data,
      status: sample.status,
      actor_id: sample.actor,
      item_id: null,
      created_at: sample.at,
      updated_at: sample.at,
    });
  }
}

function findCollection(botId: string, key: string): DataCollection {
  const col = collectionsOf(activeSpec(botId)).find((c) => c.key === key);
  if (!col) throw new ApiError("collection_not_found", "این مجموعه پیدا نشد.", 404);
  return col;
}

function writable(botId: string, key: string): DataCollection {
  const col = findCollection(botId, key);
  if (!col.writable) throw new ApiError(ERROR_CODES.readOnlyCollection, "این مجموعه فقط برای مشاهده است.", 405);
  return col;
}

const FIXTURE_NAMES: Record<string, string> = {
  "5012345701": "نگین کاظمی",
  "5012345702": "پویا صادقی",
  "5012345801": "مهسا رحیمی",
  "6001001": "زهرا موسوی",
  "6001003": "امیر نادری",
};

/** The booking/request fields the real backend adds: the customer's name and the item's title. */
function decorate(botId: string, spec: BotSpec, record: DataRecord): DataRecord {
  const out: DataRecord = { ...record };
  if (record.actor_id) out.actor_name = FIXTURE_NAMES[record.actor_id] ?? niloofarActorName(record.actor_id);
  if (record.item_id !== null) {
    const cap = spec.capabilities.find((c) => c.key === record.collection);
    const resourceKey = cap?.type === "booking" ? cap.resource : cap?.type === "request" ? cap.item_resource : null;
    const resource = spec.resources.find((r) => r.key === resourceKey);
    const item = recordsOf(botId).find((r) => r.collection === resourceKey && r.id === record.item_id);
    const title = resource && item ? item.data[resource.title_field] : null;
    out.item_title = typeof title === "string" ? title : null;
  }
  return out;
}

export function listRecords(botId: string, collection: string, page?: { limit?: number; offset?: number }): RecordsPage {
  const col = findCollection(botId, collection);
  const spec = activeSpec(botId);
  if (col.kind === "orders" && !spec.capabilities.some((c) => c.type === "orders")) seedDemoOrders(botId);
  const limit = page?.limit ?? 50;
  const offset = page?.offset ?? 0;
  const all = recordsOf(botId)
    .filter((r) => r.collection === collection)
    .sort((a, b) => b.id - a.id);
  return { collection, total: all.length, limit, offset, items: all.slice(offset, offset + limit).map((r) => decorate(botId, spec, r)) };
}

const PERSIAN_TO_ASCII: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((c, i) => (PERSIAN_TO_ASCII[c] = String(i)));
"٠١٢٣٤٥٦٧٨٩".split("").forEach((c, i) => (PERSIAN_TO_ASCII[c] = String(i)));
const ascii = (s: string) => s.replace(/[۰-۹٠-٩]/g, (c) => PERSIAN_TO_ASCII[c]);
const isEmpty = (v: unknown) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");

/** Mirrors backend/app/botspec/records.py validate_record closely enough for the same Persian errors. */
function validateRecord(
  fields: FieldDef[],
  data: Record<string, unknown>,
): { cleaned: Record<string, unknown>; errors: string[]; fieldErrors: { field: string | null; message: string }[] } {
  const cleaned: Record<string, unknown> = {};
  const errors: string[] = [];
  const fieldErrors: { field: string | null; message: string }[] = [];
  for (const f of fields) {
    const before = errors.length;
    validateField(f, data, cleaned, errors);
    for (const message of errors.slice(before)) fieldErrors.push({ field: f.key, message });
  }
  return { cleaned, errors, fieldErrors };
}

function validateField(f: FieldDef, data: Record<string, unknown>, cleaned: Record<string, unknown>, errors: string[]): void {
  {
    let raw = data[f.key];
    if (isEmpty(raw)) raw = f.default;
    if (isEmpty(raw)) {
      if (f.required) errors.push(`«${f.label}» الزامی است.`);
      cleaned[f.key] = null;
      return;
    }
    switch (f.type) {
      case "integer": {
        const s = ascii(String(raw)).trim().replace(/[,٬،_ ]/g, "");
        if (typeof raw === "boolean" || !/^[+-]?\d+$/.test(s)) errors.push(`«${f.label}» باید یک عدد صحیح باشد.`);
        else cleaned[f.key] = Number(s);
        break;
      }
      case "decimal": {
        const s = ascii(String(raw)).trim().replace("٫", ".").replace(/[,٬،_ ]/g, "");
        if (!/^[+-]?(\d+(\.\d*)?|\.\d+)$/.test(s)) errors.push(`«${f.label}» باید یک عدد باشد.`);
        else cleaned[f.key] = Number(s);
        break;
      }
      case "boolean":
        if (typeof raw === "boolean") cleaned[f.key] = raw;
        else errors.push(`«${f.label}» باید «بله» یا «خیر» باشد.`);
        break;
      case "choice":
        if (typeof raw === "string" && (f.choices ?? []).includes(raw.trim())) cleaned[f.key] = raw.trim();
        else errors.push(`«${f.label}» باید یکی از این گزینه‌ها باشد: ${(f.choices ?? []).join("، ")}`);
        break;
      case "phone": {
        const s = ascii(String(raw)).trim().replace(/[ \-()]/g, "");
        if (/^\+?\d{7,15}$/.test(s)) cleaned[f.key] = s;
        else errors.push(`«${f.label}» شمارهٔ تلفن معتبر نیست.`);
        break;
      }
      case "datetime": {
        const s = ascii(String(raw)).trim();
        if (!/(Z|[+-]\d{2}:?\d{2})$/.test(s)) {
          errors.push(Number.isNaN(Date.parse(s)) ? `«${f.label}» باید تاریخ و ساعت معتبر (ISO 8601) باشد.` : `«${f.label}» باید منطقهٔ زمانی داشته باشد.`);
        } else if (Number.isNaN(Date.parse(s))) {
          errors.push(`«${f.label}» باید تاریخ و ساعت معتبر (ISO 8601) باشد.`);
        } else {
          cleaned[f.key] = new Date(s).toISOString().replace(/\.\d{3}Z$/, "+00:00");
        }
        break;
      }
      default:
        cleaned[f.key] = String(raw).trim();
    }
  }
}

function invalid(errors: string[], fieldErrors: { field: string | null; message: string }[]): ApiError {
  return new ApiError(ERROR_CODES.invalidRecord, "داده‌های واردشده نامعتبر است: " + errors.join(" "), 400, errors, fieldErrors);
}

export function createRecord(botId: string, collection: string, data: Record<string, unknown>): DataRecord {
  const col = writable(botId, collection);
  const { cleaned, errors, fieldErrors } = validateRecord(col.fields, data);
  if (errors.length > 0) throw invalid(errors, fieldErrors);
  const d = getDb();
  d.recordSeq += 1;
  const now = new Date().toISOString();
  const record: DataRecord = { id: d.recordSeq, collection, data: cleaned, status: null, actor_id: null, item_id: null, created_at: now, updated_at: now };
  recordsOf(botId).push(record);
  persist();
  return { ...record };
}

export function updateRecord(botId: string, collection: string, recordId: number, data: Record<string, unknown>): DataRecord {
  const col = writable(botId, collection);
  const record = recordsOf(botId).find((r) => r.collection === collection && r.id === recordId);
  if (!record) throw new ApiError("record_not_found", "این رکورد پیدا نشد.", 404);
  const { cleaned, errors, fieldErrors } = validateRecord(col.fields, { ...record.data, ...data });
  if (errors.length > 0) throw invalid(errors, fieldErrors);
  record.data = { ...record.data, ...cleaned };
  record.updated_at = new Date().toISOString();
  persist();
  return { ...record };
}

export function deleteRecord(botId: string, collection: string, recordId: number): void {
  writable(botId, collection);
  const spec = activeSpec(botId);
  const records = recordsOf(botId);
  if (!records.some((r) => r.collection === collection && r.id === recordId)) {
    throw new ApiError("record_not_found", "این رکورد پیدا نشد.", 404);
  }
  for (const cap of spec.capabilities) {
    if (cap.type === "booking" && cap.resource === collection) {
      const active = records.some((r) => r.collection === cap.key && r.item_id === recordId && (r.status === "confirmed" || r.status === "waitlisted"));
      if (active) {
        throw new ApiError(
          ERROR_CODES.recordHasActiveBookings,
          "این مورد رزرو فعال یا در صف انتظار دارد و حذف نمی‌شود. ابتدا رزروها را لغو کنید.",
          409,
        );
      }
    }
  }
  getDb().records[botId] = records.filter((r) => !(r.collection === collection && r.id === recordId));
  persist();
}

export function runRecordAction(botId: string, collection: string, recordId: number, action: string): DataActionResult {
  const col = findCollection(botId, collection);
  const spec = activeSpec(botId);
  const records = recordsOf(botId);
  const record = records.find((r) => r.collection === collection && r.id === recordId);
  if (!record) throw new ApiError("record_not_found", "این رکورد پیدا نشد.", 404);
  const rejected = (cap: string, act: "cancel" | "owner_action", reason: "not_allowed", message: string): DataActionResult => ({
    ok: false,
    outcome: { capability: cap, action: act, result: "rejected", reason, record_id: recordId },
    message,
  });

  if (col.kind === "booking") {
    const cap = spec.capabilities.find((c): c is BookingCapability => c.type === "booking" && c.key === collection)!;
    if (action !== "cancel") throw new ApiError("action_not_found", "این اقدام پیدا نشد.", 404);
    if (record.status === "cancelled") return rejected(cap.key, "cancel", "not_allowed", "این ثبت‌نام قبلاً لغو شده است.");
    const wasConfirmed = record.status === "confirmed";
    record.status = "cancelled";
    record.updated_at = new Date().toISOString();
    let message = "ثبت‌نام لغو شد.";
    if (wasConfirmed && cap.waitlist.auto_promote) {
      const next = records
        .filter((r) => r.collection === collection && r.item_id === record.item_id && r.status === "waitlisted")
        .sort((a, b) => a.id - b.id)[0];
      if (next) {
        next.status = "confirmed";
        next.updated_at = record.updated_at;
        message = "ثبت‌نام لغو شد و نفر اول لیست انتظار جایگزین شد؛ به او در تلگرام اطلاع داده شد.";
      }
    }
    persist();
    return { ok: true, outcome: { capability: cap.key, action: "cancel", result: "cancelled", reason: null, record_id: recordId }, message };
  }

  if (col.kind === "request") {
    const cap = spec.capabilities.find((c): c is RequestCapability => c.type === "request" && c.key === collection)!;
    const act = cap.owner_actions.find((a) => a.key === action);
    if (!act) throw new ApiError("action_not_found", "این اقدام پیدا نشد.", 404);
    if (!record.status || !act.from_statuses.includes(record.status)) {
      return rejected(cap.key, "owner_action", "not_allowed", "این اقدام برای وضعیت فعلی درخواست ممکن نیست.");
    }
    record.status = act.to_status;
    record.updated_at = new Date().toISOString();
    persist();
    const label = cap.statuses.find((s) => s.key === act.to_status)?.label ?? act.to_status;
    return {
      ok: true,
      outcome: { capability: cap.key, action: "owner_action", result: "ok", reason: null, record_id: recordId },
      message: `وضعیت درخواست به «${label}» تغییر کرد و به مشتری در تلگرام اطلاع داده شد.`,
    };
  }
  if (col.kind === "orders") {
    const def = ordersDef(spec);
    const act = def.owner_actions.find((a) => a.key === action);
    if (!act) throw new ApiError("action_not_found", "این اقدام پیدا نشد.", 404);
    if (!record.status || !act.from_statuses.includes(record.status)) {
      return rejected(def.key, "owner_action", "not_allowed", "این اقدام برای وضعیت فعلی سفارش ممکن نیست.");
    }
    record.status = act.to_status;
    record.updated_at = new Date().toISOString();
    persist();
    const label = def.statuses.find((s) => s.key === act.to_status)?.label ?? act.to_status;
    return {
      ok: true,
      outcome: { capability: def.key, action: "owner_action", result: "ok", reason: null, record_id: recordId },
      message: `وضعیت سفارش به «${label}» تغییر کرد و به مشتری در تلگرام اطلاع داده شد.`,
    };
  }
  throw new ApiError(ERROR_CODES.readOnlyCollection, "این مجموعه اقدامی ندارد.", 405);
}

/* ------------------------------------------------------------------ telegram */
// Mirrors backend/app/integrations/telegram/onboarding.py. Owner link: a code links an owner only
// while none is linked (it never replaces one); every connect unlinks the owner and arms a fresh
// single-use code; disconnect unlinks the owner and revokes the code. The status returns a link
// exactly when opening it would link an owner.

/** onboarding.TOKEN_FORMAT: "<bot id>:<secret>", ASCII only. */
const TOKEN_FORMAT = /^([0-9]{6,}):[A-Za-z0-9_-]{30,}$/;

function statusOf(botId: string): TelegramStatus {
  const d = getDb();
  const bot = d.bots.find((b) => b.id === botId);
  if (!bot) throw new ApiError("bot_not_found", "ربات پیدا نشد.", 404);
  const connected = bot.tg_username !== null;
  const code = bot.owner_linked ? null : bot.owner_link_code; // onboarding.armed_owner_code
  return {
    connected,
    username: bot.tg_username,
    bot_link: connected ? `https://t.me/${bot.tg_username}` : null,
    owner_linked: bot.owner_linked,
    owner_link: connected && code ? `https://t.me/${bot.tg_username}?start=owner_${code}` : null,
    last_error: d.telegramErrors[botId] ?? null,
  };
}

export const getTelegram = statusOf;

export function connectTelegram(botId: string, token: string): TelegramStatus {
  const d = getDb();
  const bot = d.bots.find((b) => b.id === botId);
  if (!bot) throw new ApiError("bot_not_found", "ربات پیدا نشد.", 404);
  const match = TOKEN_FORMAT.exec(token.trim());
  // A rejected token changes nothing, not even the last error.
  if (!match) throw new ApiError("invalid_token", "توکن ربات نامعتبر است. توکن را دقیقاً از BotFather کپی کنید.", 400);
  delete d.telegramErrors[botId];
  bot.tg_username = `demo${match[1].slice(-4)}_bot`;
  bot.status = bot.status === "paused" ? "paused" : bot.active_revision_id ? "live" : "draft";
  // Every connect starts a new owner link: the owner is unlinked and a fresh code is armed.
  bot.owner_linked = false;
  bot.owner_link_code = newId("code");
  persist();
  return statusOf(botId);
}

/** onboarding / POST retry: clears a POLLING_CONFLICT error only; any other error stays. */
export function retryTelegram(botId: string): TelegramStatus {
  const d = getDb();
  if (d.telegramErrors[botId]?.startsWith("POLLING_CONFLICT:")) {
    delete d.telegramErrors[botId];
    persist();
  }
  return statusOf(botId);
}

export function disconnectTelegram(botId: string): TelegramStatus {
  const d = getDb();
  const bot = d.bots.find((b) => b.id === botId);
  if (!bot) throw new ApiError("bot_not_found", "ربات پیدا نشد.", 404);
  bot.tg_username = null;
  if (bot.status !== "paused") bot.status = "draft";
  // The owner is unlinked and any code revoked; the next connect arms a fresh one.
  bot.owner_linked = false;
  bot.owner_link_code = null;
  delete d.telegramErrors[botId];
  persist();
  return statusOf(botId);
}
