"use client";

import { useState } from "react";
import { ChatMessageList } from "@/components/simulator/chat-message-list";
import { PhoneFrame } from "@/components/simulator/phone-frame";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BUSINESS_NAME, ROLES, type RoleId } from "./data";

/**
 * One panel, three roles: the segmented control picks who is looking at the same Telegram bot. It drives one
 * sentence, a short list and one real PhoneFrame transcript (not three cards).
 */
export function RolesDemo() {
  const [role, setRole] = useState<RoleId>("customer");
  return (
    <Tabs value={role} onValueChange={(v) => setRole(v as RoleId)} className="gap-0 overflow-hidden rounded-md border border-border bg-page">
      <div className="flex items-center border-b border-border bg-surface px-4 py-3 sm:px-6">
        <TabsList variant="segmented" aria-label="نقش کاربر ربات">
          {ROLES.map((r) => (
            <TabsTrigger key={r.id} value={r.id} className="min-h-9 px-4 sm:min-h-8">
              {r.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      {ROLES.map((r) => (
        <TabsContent
          key={r.id}
          value={r.id}
          className="grid items-center gap-8 p-5 sm:p-8 lg:grid-cols-[minmax(0,30rem)_auto] lg:justify-center lg:gap-24 lg:px-14 lg:py-10"
        >
          <div className="flex max-w-xl flex-col gap-6">
            <p className="text-h2 font-semibold text-fg">{r.sentence}</p>
            <ul className="divide-y divide-border border-y border-border">
              {r.points.map((p) => (
                <li key={p} className="py-2.5 text-body text-fg-secondary">
                  {p}
                </li>
              ))}
            </ul>
          </div>
          <PhoneFrame title={BUSINESS_NAME} subtitle={r.subtitle} className="h-[31rem] w-[17.5rem] max-w-full justify-self-center">
            <ChatMessageList messages={r.messages} />
          </PhoneFrame>
        </TabsContent>
      ))}
    </Tabs>
  );
}
