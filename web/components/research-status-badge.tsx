type ResearchStatusBadgeProps = {
  status: string;
};

const labels: Record<string, string> = {
  published: "已发布",
  abstained: "已拒绝",
  aborted: "已中止",
  data_missing: "数据缺失",
  research_candidate: "研究候选",
  watch: "观察",
};

export function ResearchStatusBadge({ status }: ResearchStatusBadgeProps) {
  const tone =
    status === "published" || status === "research_candidate"
      ? "positive"
      : status === "abstained" || status === "watch"
        ? "watch"
        : "data_missing";

  return <span className={`badge ${tone}`}>{labels[status] ?? status}</span>;
}
