/**
 * @fileoverview Current review vs effective assessment panel for v0.2 detail.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type CurrentReview = {
  outcome?: unknown;
  reason?: unknown;
  run_id?: unknown;
  workflow_run_id?: unknown;
};

type EffectiveAssessment = {
  assessment_id?: unknown;
  freshness?: unknown;
  stale_reason?: unknown;
};

type CurrentVsEffectivePanelProps = {
  currentReview: CurrentReview | null;
  effectiveAssessment: EffectiveAssessment | null;
};

/** Renders the distinction between this run's review and the effective thesis. */
export function CurrentVsEffectivePanel({
  currentReview,
  effectiveAssessment,
}: CurrentVsEffectivePanelProps) {
  const outcome = text(currentReview?.outcome) || "unknown";
  const reason = text(currentReview?.reason);
  const assessmentId = text(effectiveAssessment?.assessment_id) || "暂无";
  const freshness = text(effectiveAssessment?.freshness) || "unknown";
  const staleReason = text(effectiveAssessment?.stale_reason);

  return (
    <Card aria-labelledby="current-effective-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Decision state
          </p>
          <CardTitle id="current-effective-title" className="mt-1">
            本轮复核 vs 当前有效结论
          </CardTitle>
        </div>
        <Badge tone={freshnessTone(freshness)}>{freshness}</Badge>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2">
        <article className="grid gap-1.5 rounded-md border border-border bg-muted/40 p-4">
          <strong className="text-sm font-semibold text-foreground">
            本轮复核：{outcomeLabel(outcome)}
          </strong>
          <span className="text-xs text-muted-foreground">
            {reason || "本轮未记录延期或拒绝原因"}
          </span>
          {text(currentReview?.workflow_run_id) ? (
            <span className="text-xs text-muted-foreground">
              workflow {text(currentReview?.workflow_run_id)}
            </span>
          ) : null}
        </article>
        <article className="grid gap-1.5 rounded-md border border-border bg-muted/40 p-4">
          <strong className="text-sm font-semibold text-foreground">
            当前有效结论：{assessmentId}
          </strong>
          <span className="text-xs text-muted-foreground">{freshness}</span>
          {staleReason ? (
            <span className="text-xs text-muted-foreground">{staleReason}</span>
          ) : null}
        </article>
      </CardContent>
    </Card>
  );
}

function freshnessTone(freshness: string): "positive" | "caution" | "muted" {
  if (freshness === "fresh") {
    return "positive";
  }
  if (freshness === "stale" || freshness === "deferred") {
    return "caution";
  }
  return "muted";
}

function outcomeLabel(outcome: string): string {
  if (outcome === "review_deferred") {
    return "延期";
  }
  if (outcome === "update_assessment") {
    return "更新";
  }
  if (outcome === "carry_forward_verified") {
    return "沿用已验证";
  }
  if (outcome === "invalidate_thesis") {
    return "失效候选";
  }
  if (outcome === "abstain") {
    return "拒绝结论";
  }
  return outcome;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}
