/**
 * @fileoverview Status badge component for research item lifecycle states.
 */

import { Badge, type BadgeProps } from "@/components/ui/badge";

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

function toneFor(status: string): BadgeProps["tone"] {
  if (status === "published" || status === "research_candidate") {
    return "positive";
  }
  if (status === "abstained" || status === "watch") {
    return "caution";
  }
  if (status === "data_missing") {
    return "negative";
  }
  return "muted";
}

/** Renders a styled badge for a research item status. */
export function ResearchStatusBadge({ status }: ResearchStatusBadgeProps) {
  return <Badge tone={toneFor(status)}>{labels[status] ?? status}</Badge>;
}
