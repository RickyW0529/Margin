"use client";

/**
 * @fileoverview Client-side helpers for DB-backed Agent chat history.
 */

import { useCallback, useEffect, useState } from "react";

import {
  fetchAgentChatSessions,
  type AgentChatSession,
} from "@/lib/api";

const CHANGE_EVENT = "margin-agent-chat-sessions-change";

type AgentChatSessionsState = {
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  sessions: AgentChatSession[];
};

/** Notify sidebar/listeners that the persisted Agent chat list changed. */
export function notifyAgentChatSessionsChanged(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Loads recent Agent chat sessions from the API and refreshes on local events. */
export function useAgentChatSessions(): AgentChatSessionsState {
  const [sessions, setSessions] = useState<AgentChatSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchAgentChatSessions();
      setSessions(response.items);
      setError(null);
    } catch {
      setError("failed_to_load_agent_chat_sessions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return () => undefined;
    }
    const timeoutId = window.setTimeout(() => {
      void refresh();
    }, 0);
    window.addEventListener(CHANGE_EVENT, refresh);
    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener(CHANGE_EVENT, refresh);
    };
  }, [refresh]);

  return { error, loading, refresh, sessions };
}
