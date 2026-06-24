/**
 * @fileoverview v0.2 research run progress and reconciliation component.
 */

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ResearchRunDetailV2 } from "@/lib/api";

type ResearchRunProgressProps = {
  run: ResearchRunDetailV2;
};

function statusTone(status: string): BadgeProps["tone"] {
  if (status === "succeeded") {
    return "positive";
  }
  if (status === "failed_final" || status === "cancelled") {
    return "negative";
  }
  if (status.startsWith("waiting") || status === "partial" || status === "running") {
    return "caution";
  }
  return "muted";
}

function stepTone(status: string): BadgeProps["tone"] {
  if (["succeeded", "completed", "skipped", "succeeded_with_degradation"].includes(status)) {
    return "positive";
  }
  if (["failed_final", "cancelled"].includes(status)) {
    return "negative";
  }
  if (status.startsWith("waiting") || status === "partial" || status === "failed_retryable") {
    return "caution";
  }
  return "muted";
}

/** Renders target reconciliation counts, wait state, steps, and trace metadata. */
export function ResearchRunProgress({ run }: ResearchRunProgressProps) {
  return (
    <Card aria-labelledby="run-progress-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Run reconciliation
          </p>
          <CardTitle id="run-progress-title" className="mt-1">
            运行进度
          </CardTitle>
        </div>
        <Badge tone={statusTone(run.status)}>{run.status}</Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Metric
            label="已完成"
            value={`${run.completed_count} / ${run.target_count}`}
            helper={`失败 ${run.failed_count} · 待处理 ${run.pending_count}`}
          />
          <Metric
            label="等待状态"
            value={run.wait_state ?? "none"}
            helper={waitStateText(run)}
          />
          <Metric
            label="Trace"
            value={run.trace_id ?? run.run_id}
            helper={run.supported_wait_states.join(" / ")}
          />
        </div>
        <ul className="grid gap-2">
          {run.steps.map((step, index) => (
            <li
              key={`${text(step.step) || "step"}-${index}`}
              className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2.5"
            >
              <span className="text-sm text-foreground">
                {text(step.step) || `step-${index + 1}`}
              </span>
              <Badge tone={stepTone(text(step.status))}>
                {text(step.status) || "unknown"}
              </Badge>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  value,
  helper,
}: {
  label: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="grid gap-1.5 rounded-lg border border-border bg-card p-4 shadow-sm">
      <span className="text-xs font-medium text-muted-foreground">
        {label}
      </span>
      <strong className="text-lg font-semibold tracking-tight text-foreground">
        {value}
      </strong>
      <span className="text-xs text-muted-foreground">{helper}</span>
    </div>
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
