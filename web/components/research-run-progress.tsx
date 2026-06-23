/**
 * @fileoverview v0.2 research run progress and reconciliation component.
 */

import type { ResearchRunDetailV2 } from "@/lib/api";

type ResearchRunProgressProps = {
  run: ResearchRunDetailV2;
};

/** Renders target reconciliation counts, wait state, steps, and trace metadata. */
export function ResearchRunProgress({ run }: ResearchRunProgressProps) {
  return (
    <section className="panel" aria-labelledby="run-progress-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Run reconciliation</p>
          <h2 id="run-progress-title">运行进度</h2>
        </div>
        <span>{run.status}</span>
      </div>
      <div className="metric-grid detail-metrics">
        <div className="metric-tile">
          <span>已完成</span>
          <strong>
            {run.completed_count} / {run.target_count}
          </strong>
          <span>
            失败 {run.failed_count} · 待处理 {run.pending_count}
          </span>
        </div>
        <div className="metric-tile">
          <span>等待状态</span>
          <strong>{run.wait_state ?? "none"}</strong>
          <span>{waitStateText(run)}</span>
        </div>
        <div className="metric-tile">
          <span>Trace</span>
          <strong>{run.trace_id ?? run.run_id}</strong>
          <span>{run.supported_wait_states.join(" / ")}</span>
        </div>
      </div>
      <ul className="run-step-list">
        {run.steps.map((step, index) => (
          <li key={`${text(step.step) || "step"}-${index}`}>
            <span>{text(step.step) || `step-${index + 1}`}</span>
            <strong>{text(step.status) || "unknown"}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}

function waitStateText(run: ResearchRunDetailV2): string {
  if (run.wait_state === "waiting_rate_limit") {
    return `Provider 限流，约 ${run.retry_after_seconds ?? "--"} 秒后重试`;
  }
  if (run.wait_state === "waiting_provider") {
    return "等待 Provider 恢复";
  }
  if (run.wait_state === "waiting_retry") {
    return "等待重试调度";
  }
  return "无需等待";
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}
