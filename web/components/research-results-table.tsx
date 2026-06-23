/**
 * @fileoverview Server-paginated v0.2 research candidate result table.
 */

import Link from "next/link";

import type {
  DashboardPageInfo,
  ResearchCandidateListItemV2,
} from "@/lib/api";

type ResearchResultsTableProps = {
  items: ResearchCandidateListItemV2[];
  pageInfo: DashboardPageInfo;
  scopeVersionId: string;
  universe: string;
};

const percentFormatter = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 0,
});

const scoreFormatter = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 1,
});

/**
 * Renders a stable tabular view of research candidates. The table deliberately
 * separates current review outcome from the effective assessment pointer so the
 * user can see whether today's AI review changed the persisted conclusion.
 */
export function ResearchResultsTable({
  items,
  pageInfo,
  scopeVersionId,
  universe,
}: ResearchResultsTableProps) {
  if (items.length === 0) {
    return <div className="empty-state">暂无符合当前筛选条件的研究候选</div>;
  }

  return (
    <div className="research-table-stack">
      <div className="table-scroll">
        <table aria-label="研究候选结果">
          <thead>
            <tr>
              <th scope="col">公司</th>
              <th scope="col">量化</th>
              <th scope="col">分数</th>
              <th scope="col">估值折价</th>
              <th scope="col">本轮复核</th>
              <th scope="col">有效结论</th>
              <th scope="col">纪律</th>
              <th scope="col">数据</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.item_id}>
                <td>
                  <div className="research-symbol-cell">
                    <Link className="table-link" href={`/research/items/${item.item_id}`}>
                      {item.symbol}
                    </Link>
                    <span>{item.name}</span>
                  </div>
                </td>
                <td>
                  <span className={`badge ${statusClass(item.screening_status)}`}>
                    {item.screening_status}
                  </span>
                </td>
                <td>
                  <strong>{formatScore(item.final_score)}</strong>
                  <span className="table-helper">
                    置信度 {formatPercent(item.confidence)}
                  </span>
                </td>
                <td>{formatPercent(item.discount_rate)}</td>
                <td>
                  <div className="table-stack-cell">
                    <span>本轮：{item.current_review_outcome}</span>
                    {item.review_required ? (
                      <span className="badge risk">需要复核</span>
                    ) : null}
                  </div>
                </td>
                <td>
                  <div className="table-stack-cell">
                    <span>有效：{item.effective_assessment_id ?? "暂无"}</span>
                    <span className={`badge ${statusClass(item.assessment_freshness)}`}>
                      {item.assessment_freshness}
                    </span>
                    {item.stale_reason ? (
                      <span className="table-helper">{item.stale_reason}</span>
                    ) : null}
                  </div>
                </td>
                <td>
                  <div className="table-stack-cell">
                    <span>{item.research_guardrail}</span>
                    {item.risk_flags.length > 0 ? (
                      <span className="table-helper">
                        风险 {item.risk_flags.join(" / ")}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td>
                  <div className="table-stack-cell">
                    <span>{item.data_status}</span>
                    <span className="table-helper">
                      {formatDate(item.last_checked_at)}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-pagination">
        <span>
          本页 {items.length} / page size {pageInfo.page_size}
        </span>
        {pageInfo.has_next_page && pageInfo.next_cursor ? (
          <Link
            className="secondary-link"
            href={nextHref({
              cursor: pageInfo.next_cursor,
              scopeVersionId,
              universe,
            })}
          >
            下一页
          </Link>
        ) : (
          <span className="helper-text">已到最后一页</span>
        )}
      </div>
    </div>
  );
}

function formatScore(value: number | null): string {
  return value == null ? "--" : scoreFormatter.format(value);
}

function formatPercent(value: number | null): string {
  return value == null ? "--" : percentFormatter.format(value);
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function statusClass(status: string): string {
  const normalized = status.toLowerCase().replaceAll("_", "-");
  if (["pass", "fresh", "complete"].includes(normalized)) {
    return "positive";
  }
  if (["risk-flag", "stale", "review-required"].includes(normalized)) {
    return "risk";
  }
  if (["data-insufficient", "missing"].includes(normalized)) {
    return "data_missing";
  }
  return "watch";
}

function nextHref({
  cursor,
  scopeVersionId,
  universe,
}: {
  cursor: string;
  scopeVersionId: string;
  universe: string;
}): string {
  const params = new URLSearchParams({
    cursor,
    scope_version_id: scopeVersionId,
    universe,
  });
  return `/research?${params.toString()}`;
}
