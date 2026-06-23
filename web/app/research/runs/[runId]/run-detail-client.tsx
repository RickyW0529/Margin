"use client";

/**
 * @fileoverview Polling client component for a valuation-discovery run.
 *
 * Fetches the run status, refreshes every few seconds while the run is
 * non-terminal, and renders the progress steps plus a back link once done.
 */

import { useEffect, useState } from "react";
import Link from "next/link";

import { ResearchRunProgress } from "@/components/research-run-progress";
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
    <main className="workspace-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">Valuation discovery run</p>
          <h1>{run?.run_id ?? runId}</h1>
        </div>
        <div className="status-strip">
          <span>{run?.status ?? "--"}</span>
          <span>{run?.target_count ?? 0} 个编排步骤</span>
          {polling ? <span>自动刷新中</span> : null}
        </div>
      </section>
      {error ? (
        <div className="notice-panel" role="alert">
          <span>{error}</span>
        </div>
      ) : null}
      <div className="side-rail">
        {run ? <ResearchRunProgress run={run} /> : null}
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Dashboard projection</p>
              <h2>研究候选结果</h2>
            </div>
            <span>由 effective assessment 指针驱动</span>
          </div>
          <p className="helper-text">
            运行完成后，请在研究候选面板按 scope、公司池、筛选状态和证据状态查看当前可见结果。
          </p>
          <Link className="secondary-link" href="/research">
            返回研究候选面板
          </Link>
        </section>
      </div>
    </main>
  );
}