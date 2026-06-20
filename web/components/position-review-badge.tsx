/**
 * @fileoverview Status badge component for portfolio position review states.
 */

/** Props for the PositionReviewBadge component. */
type PositionReviewBadgeProps = {
  /** Position review status identifier, or null when unbound. */
  status: string | null;
};

/** Localized labels mapped by position review status. */
const labels: Record<string, string> = {
  THESIS_VALID: "逻辑有效",
  REVIEW_REQUIRED: "需要复核",
  RISK_ALERT: "风险提醒",
  THESIS_INVALIDATED: "逻辑失效",
};

/**
 * Renders a styled badge for a position review status.
 *
 * @param status Position review status identifier, or null.
 * @returns The localized review badge element.
 */
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
