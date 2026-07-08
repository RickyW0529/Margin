"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchResearchRunDetailV2,
  fetchValuationDiscoveryRuns,
  startValuationDiscoveryRefresh,
  type ResearchRunDetailV2,
  type ValuationDiscoveryRefreshCreate,
  type ValuationDiscoveryRefreshStart,
} from "@/lib/api";
import {
  isRefreshRunPollingState,
  isRefreshRunTerminalState,
} from "@/lib/refresh-run-graph";

const POLL_INTERVAL_MS = 3000;
const DISMISSED_RUN_STORAGE_KEY = "margin.dashboard.dismissedRefreshRunId";

type LatestRunSummary = {
  run_id: string;
  state?: string;
};

type UseDashboardRefreshRunOptions = {
  fetchLatestRun?: () => Promise<LatestRunSummary | null>;
  fetchRunDetail?: (runId: string) => Promise<ResearchRunDetailV2>;
  now?: () => Date;
  onRunSettled?: (run: ResearchRunDetailV2) => void;
  startRefresh?: (
    refresh: ValuationDiscoveryRefreshCreate,
  ) => Promise<ValuationDiscoveryRefreshStart>;
};

export type DashboardRefreshRunState = {
  busy: boolean;
  error: string | null;
  latestRun: ResearchRunDetailV2 | null;
  latestRunId: string | null;
  open: boolean;
  refreshInProgress: boolean;
  setOpen: (open: boolean) => void;
  start: () => Promise<void>;
};

/** Owns the dashboard's newest refresh run and live polling lifecycle. */
export function useDashboardRefreshRun({
  fetchLatestRun = defaultFetchLatestRun,
  fetchRunDetail = fetchResearchRunDetailV2,
  now = () => new Date(),
  onRunSettled,
  startRefresh = startValuationDiscoveryRefresh,
}: UseDashboardRefreshRunOptions = {}): DashboardRefreshRunState {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latestRun, setLatestRun] = useState<ResearchRunDetailV2 | null>(null);
  const [latestRunId, setLatestRunId] = useState<string | null>(null);
  const [open, setOpenState] = useState(false);
  const dismissedRunId = useRef<string | null>(null);
  const settledRunId = useRef<string | null>(null);
  const startLocked = useRef(false);

  const loadRun = useCallback(
    async (runId: string) => {
      const detail = await fetchRunDetail(runId);
      setLatestRun((current) => (current?.run_id === runId ? detail : detail));
      return detail;
    },
    [fetchRunDetail],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        dismissedRunId.current = readDismissedRunId();
        const latest = await fetchLatestRun();
        if (cancelled || !latest?.run_id) {
          return;
        }
        setLatestRunId(latest.run_id);
        setOpenState(shouldAutoOpenRun(latest.run_id, latest.state, dismissedRunId.current));
        const detail = await fetchRunDetail(latest.run_id);
        if (!cancelled) {
          setLatestRun(detail);
          setOpenState(
            (current) =>
              current ||
              shouldAutoOpenRun(detail.run_id, detail.status, dismissedRunId.current),
          );
        }
      } catch {
        if (!cancelled) {
          setError("最近一次刷新状态暂时不可用");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchLatestRun, fetchRunDetail]);

  useEffect(() => {
    if (!latestRunId || !isRefreshRunPollingState(latestRun?.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      loadRun(latestRunId).catch(() => {
        setError("刷新状态暂时不可用");
      });
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [latestRun?.status, latestRunId, loadRun]);

  useEffect(() => {
    if (
      !latestRun ||
      !isRefreshRunTerminalState(latestRun.status) ||
      settledRunId.current === latestRun.run_id
    ) {
      return;
    }
    settledRunId.current = latestRun.run_id;
    onRunSettled?.(latestRun);
  }, [latestRun, onRunSettled]);

  const setOpen = useCallback(
    (nextOpen: boolean) => {
      setOpenState(nextOpen);
      if (!latestRunId) {
        return;
      }
      if (nextOpen) {
        if (dismissedRunId.current === latestRunId) {
          dismissedRunId.current = null;
          clearDismissedRunId();
        }
        return;
      }
      dismissedRunId.current = latestRunId;
      writeDismissedRunId(latestRunId);
    },
    [latestRunId],
  );

  const refreshInProgress =
    busy ||
    Boolean(
      latestRunId &&
        (latestRun === null || isRefreshRunPollingState(latestRun.status)),
    );

  async function start(): Promise<void> {
    if (startLocked.current || refreshInProgress) {
      return;
    }
    startLocked.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await startRefresh({
        decision_at: now().toISOString(),
        scope_version_id: "scope-current",
      });
      setLatestRun(null);
      setLatestRunId(result.run_id);
      dismissedRunId.current = null;
      clearDismissedRunId();
      setOpenState(true);
      await loadRun(result.run_id);
    } catch (caught) {
      setError(refreshErrorMessage(caught));
    } finally {
      startLocked.current = false;
      setBusy(false);
    }
  }

  return {
    busy,
    error,
    latestRun,
    latestRunId,
    open,
    refreshInProgress,
    setOpen,
    start,
  };
}

function defaultFetchLatestRun(): Promise<LatestRunSummary | null> {
  return fetchValuationDiscoveryRuns({ limit: 1 }).then(
    (response) => response.items[0] ?? null,
  );
}

function shouldAutoOpenRun(
  runId: string,
  status: string | undefined,
  dismissedRunId: string | null,
): boolean {
  return isRefreshRunPollingState(status) && dismissedRunId !== runId;
}

function readDismissedRunId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.sessionStorage.getItem(DISMISSED_RUN_STORAGE_KEY);
}

function writeDismissedRunId(runId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(DISMISSED_RUN_STORAGE_KEY, runId);
}

function clearDismissedRunId(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(DISMISSED_RUN_STORAGE_KEY);
}

function refreshErrorMessage(caught: unknown): string {
  if (
    caught instanceof Error &&
    caught.message.includes("service_not_configured")
  ) {
    return "搜索服务还没配置好，请先到设置里检查密钥配置。";
  }
  return "启动失败，请稍后重试，或到设置页检查配置。";
}
