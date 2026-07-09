"use client";

/**
 * @fileoverview Dashboard control for starting and inspecting the latest refresh.
 */

import { ChevronDown, ChevronUp, RefreshCw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useState } from "react";

import { AgentCollaborationFeed } from "@/components/agent-collaboration-feed";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDashboardRefreshRun } from "@/hooks/use-dashboard-refresh-run";
import type { ResearchRunDetailV2 } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

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
  const { t } = useLanguage();
  const titleId = useId();
  const descriptionId = useId();
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
  const [dialogOverride, setDialogOverride] = useState<{
    open: boolean;
    runId: string | null;
  } | null>(null);
  const overrideOpen =
    dialogOverride?.runId === state.latestRunId ? dialogOverride.open : null;
  const progressVisible = Boolean(
    state.latestRunId && (overrideOpen ?? state.open),
  );

  const openProgress = useCallback(() => {
    setDialogOverride({ open: true, runId: state.latestRunId });
    state.setOpen(true);
  }, [state]);

  const closeProgress = useCallback(() => {
    setDialogOverride({ open: false, runId: state.latestRunId });
    state.setOpen(false);
  }, [state]);

  const progressValue = estimateProgress(state.latestRun, state.refreshInProgress);

  // Escape closes the progress surface (same as a true modal dialog).
  useEffect(() => {
    if (!progressVisible) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeProgress();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeProgress, progressVisible]);

  return (
    <TooltipProvider delayDuration={200}>
      <div className="grid w-full justify-items-start gap-2 md:justify-items-end">
        <div className="flex flex-wrap items-center justify-start gap-2 md:justify-end">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                data-testid="dashboard-refresh-start"
                disabled={state.refreshInProgress}
                loading={state.busy}
                onClick={state.start}
                size="lg"
                type="button"
              >
                <RefreshCw className="size-4" />
                {state.refreshInProgress ? t("refreshRunning") : t("refreshStart")}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {state.refreshInProgress ? t("refreshRunning") : t("refreshStart")}
            </TooltipContent>
          </Tooltip>
          {state.latestRunId && !progressVisible ? (
            <GraphToggle
              closeLabel={t("refreshCloseGraph")}
              openLabel={t("refreshOpenGraph")}
              open={progressVisible}
              onToggle={openProgress}
            />
          ) : null}
        </div>
        {state.refreshInProgress ? (
          <div className="w-full max-w-sm">
            <Progress value={progressValue} />
          </div>
        ) : null}
        {state.error ? (
          <p
            className="max-w-sm rounded-xl border border-negative/15 bg-negative-soft px-3 py-2 text-xs leading-relaxed text-negative"
            role="alert"
          >
            {state.error}
          </p>
        ) : null}

        {state.latestRunId && progressVisible ? (
          <section
            aria-describedby={descriptionId}
            aria-labelledby={titleId}
            aria-modal="true"
            className="fixed inset-0 z-50 grid place-items-center bg-foreground/30 px-4 py-6 backdrop-blur-[2px]"
            data-testid="dialog-overlay"
            onClick={(event) => {
              // Clicking the dimmed backdrop (not the panel) dismisses.
              if (event.target === event.currentTarget) {
                closeProgress();
              }
            }}
            role="dialog"
          >
            <div className="w-[min(96vw,1080px)] animate-in fade-in zoom-in-95 duration-200 overflow-hidden rounded-2xl border border-border/90 bg-card shadow-lg">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/80 px-5 py-4">
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
                    {t("refreshLatest")}
                  </p>
                  <h2
                    className="mt-1 text-sm font-semibold tracking-tight text-foreground"
                    id={titleId}
                  >
                    {t("refreshGraphTitle")}
                  </h2>
                  <p
                    className="mt-1 max-w-xl truncate text-xs text-muted-foreground"
                    id={descriptionId}
                  >
                    {state.latestRun?.run_id ?? state.latestRunId}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-border/80 bg-muted/60 px-2.5 py-1 text-xs text-muted-foreground">
                      {state.latestRun?.status ?? t("refreshLoading")}
                    </span>
                    <div className="min-w-40 flex-1">
                      <Progress value={progressValue} />
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    onClick={closeProgress}
                    size="sm"
                    type="button"
                    variant="secondary"
                  >
                    {t("refreshCloseGraph")}
                  </Button>
                  <button
                    aria-label="关闭"
                    className="grid size-9 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    type="button"
                    onClick={closeProgress}
                  >
                    <X className="size-4" />
                  </button>
                </div>
              </div>
              <div className="max-h-[70vh] overflow-y-auto p-4">
                <AgentCollaborationFeed run={state.latestRun} />
              </div>
            </div>
          </section>
        ) : null}
      </div>
    </TooltipProvider>
  );
}

function GraphToggle({
  closeLabel,
  onToggle,
  open,
  openLabel,
}: {
  closeLabel: string;
  onToggle: () => void;
  open: boolean;
  openLabel: string;
}) {
  const Icon = open ? ChevronUp : ChevronDown;
  return (
    <Button onClick={onToggle} size="sm" type="button" variant="secondary">
      <Icon className="size-4" />
      {open ? closeLabel : openLabel}
    </Button>
  );
}

function estimateProgress(
  run: ResearchRunDetailV2 | null | undefined,
  running: boolean,
): number {
  if (!run) {
    return running ? 18 : 0;
  }
  const total = Math.max(run.target_count || run.steps?.length || 0, 1);
  const completed = Math.max(run.completed_count || 0, 0);
  const ratio = Math.round((completed / total) * 100);
  if (running) {
    return Math.min(96, Math.max(12, ratio || 18));
  }
  return Math.min(100, ratio);
}
