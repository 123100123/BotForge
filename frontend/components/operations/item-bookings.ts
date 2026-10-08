"use client";

import { useCallback, useMemo } from "react";
import { useCollectionRecords } from "@/components/data/use-collection-records";
import type { DataCollection, DataRecord, FieldDef } from "@/lib/types";

export interface BookingStats {
  confirmed: number;
  waitlisted: number;
  cancelled: number;
}

/** The fields of a bookable item (an event, a workshop, a slot) that the views care about. */
export interface ItemFields {
  title: FieldDef | undefined;
  start: FieldDef | undefined;
  category: FieldDef | undefined;
  location: FieldDef | undefined;
  capacity: FieldDef | undefined;
}

export function itemFields(resource: DataCollection): ItemFields {
  const fields = resource.fields;
  const byKey = (k: string, type?: FieldDef["type"]) => fields.find((f) => f.key === k && (!type || f.type === type));
  return {
    title: fields.find((f) => f.key === resource.title_field) ?? fields[0],
    start: byKey("starts_at", "datetime") ?? fields.find((f) => f.type === "datetime"),
    category: byKey("category", "choice") ?? fields.find((f) => f.type === "choice"),
    location: byKey("location") ?? undefined,
    capacity: byKey("capacity", "integer") ?? undefined,
  };
}

export function itemStartMs(item: DataRecord, fields: ItemFields): number | null {
  const v = fields.start ? item.data[fields.start.key] : undefined;
  if (typeof v !== "string" || !v) return null;
  const t = new Date(v).getTime();
  return Number.isNaN(t) ? null : t;
}

export function itemCapacity(item: DataRecord, fields: ItemFields): number | null {
  const v = fields.capacity ? item.data[fields.capacity.key] : undefined;
  const n = typeof v === "number" ? v : Number(v);
  return v === undefined || v === null || v === "" || !Number.isFinite(n) || n <= 0 ? null : n;
}

export function itemText(item: DataRecord, field: FieldDef | undefined): string {
  const v = field ? item.data[field.key] : undefined;
  return typeof v === "string" ? v : v === undefined || v === null ? "" : String(v);
}

const EMPTY: BookingStats = { confirmed: 0, waitlisted: 0, cancelled: 0 };

/** Bookings of one booking collection joined to its items by `item_id`. */
export function useItemsAndBookings(botId: string, booking: DataCollection | undefined, resource: DataCollection | undefined) {
  const items = useCollectionRecords(botId, resource?.key ?? null, { loadAll: true });
  const bookings = useCollectionRecords(botId, booking?.key ?? null, { loadAll: true });

  const stats = useMemo(() => {
    const map = new Map<number, BookingStats>();
    for (const b of bookings.items ?? []) {
      if (b.item_id === null) continue;
      const s = map.get(b.item_id) ?? { ...EMPTY };
      if (b.status === "confirmed") s.confirmed += 1;
      else if (b.status === "waitlisted") s.waitlisted += 1;
      else if (b.status === "cancelled") s.cancelled += 1;
      map.set(b.item_id, s);
    }
    return map;
  }, [bookings.items]);

  const bookingsOf = useCallback((itemId: number) => (bookings.items ?? []).filter((b) => b.item_id === itemId), [bookings.items]);
  const reloadBookings = bookings.reload;
  const reloadItems = items.reload;
  const reloadAll = useCallback(() => {
    reloadBookings();
    reloadItems();
  }, [reloadBookings, reloadItems]);

  return {
    items: items.items,
    bookings: bookings.items,
    stats,
    statsOf: (id: number): BookingStats => stats.get(id) ?? EMPTY,
    bookingsOf,
    error: items.error ?? bookings.error,
    reloadItems,
    reloadBookings,
    reloadAll,
  };
}
