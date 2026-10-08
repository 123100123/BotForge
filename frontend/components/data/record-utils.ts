import { fa, toFaDigits } from "@/lib/format";
import type { DataCollection, DataRecord } from "@/lib/types";

/** The title of a record: its collection's title field, else the item title, else a generic name with the id. */
export function recordTitle(record: DataRecord, collection: DataCollection | undefined): string {
  const key = collection?.title_field;
  const fromField = key ? record.data[key] : undefined;
  const candidate = fromField ?? record.item_title ?? record.data.title ?? record.data.name;
  if (typeof candidate === "string" && candidate.trim()) return candidate;
  return `${collection?.label ?? "مورد"} ${fa(record.id)}`;
}

/** Who sent a booking / request / order: the customer's name, else the Telegram id in a left-to-right run. */
export function actorLabel(record: DataRecord): { text: string; ltr: boolean } {
  if (record.actor_name) return { text: record.actor_name, ltr: false };
  if (record.actor_id) return { text: toFaDigits(record.actor_id), ltr: true };
  return { text: "—", ltr: false };
}

/** What a request is about: the item it names, else its first filled text-like field. */
export function subjectOf(record: DataRecord, collection: DataCollection): string {
  if (record.item_title) return record.item_title;
  for (const f of collection.fields) {
    if (f.type !== "text" && f.type !== "long_text" && f.type !== "choice") continue;
    const v = record.data[f.key];
    if (typeof v === "string" && v.trim()) return v.split(/\r?\n/)[0].trim();
  }
  return "";
}
