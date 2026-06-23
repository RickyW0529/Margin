/**
 * @fileoverview Current review vs effective assessment panel for v0.2 detail.
 */

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
    <section className="panel" aria-labelledby="current-effective-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Decision state</p>
          <h2 id="current-effective-title">本轮复核 vs 当前有效结论</h2>
        </div>
        <span>{freshness}</span>
      </div>
      <div className="current-effective-grid">
        <article>
          <strong>本轮复核：{outcomeLabel(outcome)}</strong>
          <span>{reason || "本轮未记录延期或拒绝原因"}</span>
          {text(currentReview?.workflow_run_id) ? (
            <span>workflow {text(currentReview?.workflow_run_id)}</span>
          ) : null}
        </article>
        <article>
          <strong>当前有效结论：{assessmentId}</strong>
          <span>{freshness}</span>
          {staleReason ? <span>{staleReason}</span> : null}
        </article>
      </div>
    </section>
  );
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
