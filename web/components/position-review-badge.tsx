type PositionReviewBadgeProps = {
  status: string | null;
};

const labels: Record<string, string> = {
  THESIS_VALID: "逻辑有效",
  REVIEW_REQUIRED: "需要复核",
  RISK_ALERT: "风险提醒",
  THESIS_INVALIDATED: "逻辑失效",
};

export function PositionReviewBadge({ status }: PositionReviewBadgeProps) {
  if (!status) {
    return <span className="badge">未绑定组合</span>;
  }

  const tone = status.includes("RISK") || status.includes("INVALID")
    ? "data_missing"
    : status.includes("REVIEW")
      ? "watch"
      : "positive";

  return <span className={`badge ${tone}`}>{labels[status] ?? status}</span>;
}
