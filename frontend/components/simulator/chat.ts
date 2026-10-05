import type { OutMessage, Persona, RuntimeButton, RuntimeResponse } from "@/lib/types";

export const PERSONAS: { id: Persona; label: string }[] = [
  { id: "ali", label: "علی" },
  { id: "sara", label: "سارا" },
  { id: "reza", label: "رضا" },
  { id: "staff", label: "همکار" },
  { id: "owner", label: "مدیر" },
];

export const PERSONA_IDS: readonly string[] = PERSONAS.map((p) => p.id);

export interface ChatItem {
  id: number;
  from: "bot" | "me";
  text: string;
  buttons: RuntimeButton[][];
}

export type Chats = Record<Persona, ChatItem[]>;
export type Unread = Record<Persona, number>;

export const emptyChats = (): Chats => ({ ali: [], sara: [], reza: [], staff: [], owner: [] });
export const emptyUnread = (): Unread => ({ ali: 0, sara: 0, reza: 0, staff: 0, owner: 0 });

/**
 * Applies a RuntimeResponse to the per-persona transcripts. A message with `edit: true` addressed
 * to the acting persona replaces the bot message whose button was pressed (`sourceId`), or else the
 * persona's latest bot message; every other message is appended. Messages addressed to personas
 * other than the acting one raise their unread count.
 */
export function applyResponse(
  chats: Chats,
  unread: Unread,
  acting: Persona,
  response: RuntimeResponse,
  sourceId: number | null,
  nextId: () => number,
): { chats: Chats; unread: Unread } {
  const nextChats: Chats = { ali: chats.ali, sara: chats.sara, reza: chats.reza, staff: chats.staff, owner: chats.owner };
  const nextUnread: Unread = { ...unread };

  for (const m of response.messages as OutMessage[]) {
    if (!PERSONA_IDS.includes(m.to_actor_id)) continue; // not a simulator persona
    const target = m.to_actor_id as Persona;
    const item = (id: number): ChatItem => ({ id, from: "bot", text: m.text, buttons: m.buttons });
    const list = nextChats[target];

    if (m.edit && target === acting) {
      let index = sourceId !== null ? list.findIndex((c) => c.id === sourceId && c.from === "bot") : -1;
      if (index === -1) index = findLastBot(list);
      if (index !== -1) {
        nextChats[target] = list.map((c, i) => (i === index ? { ...c, text: m.text, buttons: m.buttons } : c));
        continue;
      }
    }
    nextChats[target] = [...list, item(nextId())];
    if (target !== acting) nextUnread[target] += 1;
  }
  return { chats: nextChats, unread: nextUnread };
}

function findLastBot(list: ChatItem[]): number {
  for (let i = list.length - 1; i >= 0; i -= 1) if (list[i].from === "bot") return i;
  return -1;
}
