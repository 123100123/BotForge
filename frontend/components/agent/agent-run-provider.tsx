"use client";

import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useAgentRun, type AgentRunController } from "./use-agent-run";

/**
 * The business's agent run (build or change), owned by the bot layout so its event stream and state
 * survive navigating between sections (D03). The Changes page renders it; the shell reads
 * `awaitingOwner` for the «تغییرات» badge.
 */
export interface AgentRunContextValue extends AgentRunController {
  /** A proposal waits for the owner: an answer (waiting_user) or an approval (waiting_approval). */
  awaitingOwner: boolean;
}

const AgentRunContext = createContext<AgentRunContextValue | null>(null);

export function useAgentRunContext(): AgentRunContextValue {
  const ctx = useContext(AgentRunContext);
  if (!ctx) throw new Error("useAgentRunContext must be used inside AgentRunProvider (the bot layout)");
  return ctx;
}

/** The run context when rendered under /bots/[id], otherwise null. */
export function useOptionalAgentRun(): AgentRunContextValue | null {
  return useContext(AgentRunContext);
}

export function AgentRunProvider({
  botId,
  onDeployed,
  children,
}: {
  botId: string;
  /** A version was activated by the run: the bot (and its collections) changed on the server. */
  onDeployed: () => void;
  children: ReactNode;
}) {
  const agent = useAgentRun(botId);

  // Lives here, not in the Changes page, so an approval that lands while the owner is elsewhere still
  // refreshes the bot, the sidebar and the active version.
  const deployed = useMemo(() => agent.view.feed.find((i) => i.kind === "deployed")?.id ?? null, [agent.view.feed]);
  useEffect(() => {
    if (deployed !== null) onDeployed();
    // onDeployed is a stable reload callback; only a new deployment should trigger it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deployed]);

  const awaitingOwner = agent.status === "waiting_user" || agent.status === "waiting_approval";
  const value: AgentRunContextValue = { ...agent, awaitingOwner };
  return <AgentRunContext.Provider value={value}>{children}</AgentRunContext.Provider>;
}
