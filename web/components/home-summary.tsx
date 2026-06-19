import type { ResearchHomeSummary } from "@/lib/api";

type HomeSummaryProps = {
  summary: ResearchHomeSummary | null;
};

function stat(summary: ResearchHomeSummary | null, key: string): number {
  return summary?.run_stats[key] ?? 0;
}

export function HomeSummary({ summary }: HomeSummaryProps) {
  return (
    <section className="metric-grid" aria-label="研究首页摘要">
      <SummaryTile
        title="市场状态摘要"
        value={summary?.run_status ?? "暂无运行"}
        helper={summary?.decision_at?.slice(0, 10) ?? "--"}
      />
      <SummaryTile
        title="今日候选"
        value={`${summary?.today_candidates.length ?? 0} 个候选`}
        helper={`${stat(summary, "item_count")} 个研究项`}
      />
      <SummaryTile
        title="现有持仓复核"
        value={`${summary?.position_reviews.length ?? 0} 个提醒`}
        helper={summary?.run_id ? `run ${summary.run_id}` : "等待组合绑定"}
      />
      <SummaryTile
        title="高优先级风险"
        value={`${summary?.high_priority_risks.length ?? 0} 个风险`}
        helper={`${stat(summary, "abstained_count")} 个拒绝/放弃`}
      />
      <SummaryTile
        title="拒绝判断"
        value={`${summary?.rejections.length ?? 0} 条`}
        helper="已记录拒绝原因"
      />
      <SummaryTile
        title="策略运行状态"
        value={summary?.version_id ?? "--"}
        helper={summary?.strategy_id ?? "--"}
      />
    </section>
  );
}

function SummaryTile({
  title,
  value,
  helper,
}: {
  title: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="metric-tile">
      <span>{title}</span>
      <strong>{value}</strong>
      <span>{helper}</span>
    </div>
  );
}
