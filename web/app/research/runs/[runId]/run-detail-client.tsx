"use client";

/**
 * @fileoverview Polling client component for a valuation-discovery run.
 */

import { useEffect, useState } from "react";
import Link from "next/link";

import { ResearchRunProgress } from "@/components/research-run-progress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchResearchRunDetailV2,
  type ResearchRunDetailV2,
} from "@/lib/api";

const POLL_INTERVAL_MS = 3000;
const TERMINAL_STATES = new Set([
  "succeeded",
  "failed_final",
  "cancelled",
  "skipped",
]);

/** Loads and polls a run by id, returning the rendered page content. */
export function runDetailPageLoader(runId: string) {
  return <RunDetailClient runId={runId} />;
}

type RunDetailClientProps = { runId: string };

function RunDetailClient({ runId }: RunDetailClientProps) {
  const [run, setRun] = useState<ResearchRunDetailV2 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const detail = await fetchResearchRunDetailV2(runId);
        if (!cancelled) {
          setRun(detail);
          setError(null);
          if (TERMINAL_STATES.has(detail.status)) {
            setPolling(false);
          }
        }
      } catch {
        if (!cancelled) {
          setError("研究运行数据暂时不可用");
          setPolling(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  useEffect(() => {
    if (!polling) {
      return;
    }
    const timer = window.setInterval(() => {
      (async () => {
        try {
          const detail = await fetchResearchRunDetailV2(runId);
          setRun(detail);
          if (TERMINAL_STATES.has(detail.status)) {
            setPolling(false);
          }
        } catch {
          setPolling(false);
        }
      })();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [polling, runId]);

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-8 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Valuation discovery run
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
            {run?.run_id ?? runId}
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {run?.status ?? "--"}
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {run?.target_count ?? 0} 个编排步骤
          </span>
          {polling ? (
            <span className="inline-flex items-center rounded-full border border-caution-soft bg-caution-soft px-2.5 py-1 text-xs font-medium text-caution">
              自动刷新中
            </span>
          ) : null}
        </div>
      </header>

      {error ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      <div className="grid gap-6">
        {run ? <ResearchRunProgress run={run} /> : null}
        <Card>
          <CardHeader>
            <div>
              <p className="text-xs font-medium uppercase tracking-wider text-accent">
                Dashboard projection
              </p>
              <CardTitle className="mt-1">研究候选结果</CardTitle>
            </div>
            <span className="text-xs text-muted-foreground">
              由 effective assessment 指针驱动
            </span>
          </CardHeader>
          <CardContent className="grid gap-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              运行完成后，请在研究候选面板按 scope、公司池、筛选状态和证据状态查看当前可见结果。
            </p>
            <Button asChild variant="secondary" size="sm">
              <Link href="/research">返回研究候选面板</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
