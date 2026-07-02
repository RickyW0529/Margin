"use client";

/**
 * @fileoverview Dashboard control for starting and inspecting the latest refresh.
 */

import { ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { DashboardRefreshNodeGraph } from "@/components/dashboard-refresh-node-graph";
import { Button } from "@/components/ui/button";
import {
  useDashboardRefreshRun,
  type DashboardRefreshRunState,
} from "@/hooks/use-dashboard-refresh-run";
import type { ResearchRunDetailV2 } from "@/lib/api";

type DashboardRefreshControlProps = Parameters<
  typeof useDashboardRefreshRun
>[0] extends infer Props
  ? NonNullable<Props>
  : never;

/** Starts today's research and shows only the newest refresh run graph. */
export function DashboardRefreshControl({
  onRunSettled,
  ...props
}: DashboardRefreshControlProps) {
  const router = useRouter();
  const handleRunSettled = useCallback(
    (run: ResearchRunDetailV2) => {
      onRunSettled?.(run);
      router.refresh();
    },
    [onRunSettled, router],
  );
  const state = useDashboardRefreshRun({
    ...props,
    onRunSettled: handleRunSettled,
  });

  return (
    <div className="grid w-full justify-items-start gap-2 md:justify-items-end">
      <div className="flex flex-wrap items-center justify-start gap-2 md:justify-end">
        <Button
          disabled={state.refreshInProgress}
          loading={state.busy}
          onClick={state.start}
          size="lg"
          type="button"
        >
          <RefreshCw className="size-4" />
          {state.refreshInProgress ? "刷新进行中" : "刷新今日研究"}
        </Button>
        {state.latestRunId && !state.open ? <GraphToggle state={state} /> : null}
      </div>
      {state.error ? (
        <p
          className="max-w-sm rounded-md border border-negative-soft bg-negative-soft px-3 py-2 text-xs leading-relaxed text-negative"
          role="alert"
        >
          {state.error}
        </p>
      ) : null}
      {state.latestRunId && state.open ? (
        <section
          aria-label="最近一次刷新节点图"
          aria-modal="true"
          className="fixed inset-0 z-50 grid place-items-center bg-background/70 px-4 py-6 backdrop-blur-sm"
          role="dialog"
        >
          <div className="w-[min(96vw,1080px)] animate-in fade-in zoom-in-95 duration-200 rounded-lg border border-border bg-card shadow-lg">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-accent">
                  Latest refresh
                </p>
                <h2 className="mt-1 text-sm font-semibold text-foreground">
                  最近一次刷新节点图
                </h2>
                <p className="mt-1 max-w-xl truncate text-xs text-muted-foreground">
                  {state.latestRun?.run_id ?? state.latestRunId}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                  {state.latestRun?.status ?? "loading"}
                </span>
                <Button
                  onClick={() => state.setOpen(false)}
                  size="sm"
                  type="button"
                  variant="secondary"
                >
                  收起节点图
                </Button>
              </div>
            </div>
            <div className="p-3">
              <DashboardRefreshNodeGraph run={state.latestRun} />
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function GraphToggle({ state }: { state: DashboardRefreshRunState }) {
  const Icon = state.open ? ChevronUp : ChevronDown;
  return (
    <Button
      onClick={() => state.setOpen(!state.open)}
      size="sm"
      type="button"
      variant="secondary"
    >
      <Icon className="size-4" />
      {state.open ? "收起节点图" : "打开节点图"}
    </Button>
  );
}
