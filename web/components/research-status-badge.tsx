/**
 * @fileoverview Status badge component for research item lifecycle states.
 */

/** Props for the ResearchStatusBadge component. */
type ResearchStatusBadgeProps = {
  /** Research status identifier. */
  status: string;
};

/** Localized labels mapped by research status. */
const labels: Record<string, string> = {
  published: "已发布",
  abstained: "已拒绝",
  aborted: "已中止",
  data_missing: "数据缺失",
  research_candidate: "研究候选",
  watch: "观察",
};

/**
 * Renders a styled badge for a research item status.
 *
 * @param status Research status identifier.
 * @returns The localized status badge element.
 */
export function ResearchStatusBadge({ status }: ResearchStatusBadgeProps) {
  const tone =
    status === "published" || status === "research_candidate"
      ? "positive"
      : status === "abstained" || status === "watch"
        ? "watch"
        : "data_missing";

  return <span className={`badge ${tone}`}>{labels[status] ?? status}</span>;
}
