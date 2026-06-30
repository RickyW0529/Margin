/**
 * @fileoverview Server-paginated v0.2 research candidate result table.
 */

import Link from "next/link";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DashboardPageInfo, ResearchCandidateListItemV2 } from "@/lib/api";
import { formatDate, formatPercent, formatScore } from "@/lib/utils";

type ResearchResultsTableProps = {
  items: ResearchCandidateListItemV2[];
  pageInfo: DashboardPageInfo;
  scopeVersionId: string;
  universe: string;
};

function statusTone(status: string): BadgeProps["tone"] {
  const normalized = status.toLowerCase().replaceAll("_", "-");
  if (["pass", "fresh", "complete"].includes(normalized)) {
    return "positive";
  }
  if (
    ["risk-flag", "stale", "review-required", "near-threshold", "watchlist"].includes(
      normalized,
    )
  ) {
    return "caution";
  }
  if (["data-insufficient", "missing", "reject"].includes(normalized)) {
    return "negative";
  }
  return "muted";
}

/** Renders research candidates with current/effective split and cursor pagination. */
export function ResearchResultsTable({
  items,
  pageInfo,
  scopeVersionId,
  universe,
}: ResearchResultsTableProps) {
  if (items.length === 0) {
    return (
      <div className="grid place-items-center rounded-md border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
        暂无符合当前筛选条件的研究候选
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table
          className="w-full min-w-[860px] border-collapse text-sm"
          aria-label="研究候选结果"
        >
          <thead>
            <tr className="border-b border-border bg-muted/50 text-left">
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                公司
              </th>
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                量化
              </th>
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                分数
              </th>
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                估值折价
              </th>
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                本轮复核
              </th>
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                有效结论
              </th>
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                纪律
              </th>
              <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                数据
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.item_id}
                className="border-b border-border transition-colors last:border-b-0 hover:bg-muted/30"
              >
                <td className="px-3 py-3">
                  <div className="grid gap-0.5">
                    <Link
                      href={`/research/items/${item.item_id}`}
                      className="text-sm font-semibold text-accent no-underline hover:underline"
                    >
                      {item.symbol}
                    </Link>
                    <span className="text-xs text-muted-foreground">
                      {item.name}
                    </span>
                    <Link
                      href={`/research/companies/${encodeURIComponent(item.security_id)}`}
                      className="text-xs text-muted-foreground no-underline hover:text-accent hover:underline"
                    >
                      量化指标 →
                    </Link>
                  </div>
                </td>
                <td className="px-3 py-3">
                  <Badge tone={statusTone(item.screening_status)}>
                    {item.screening_status}
                  </Badge>
                </td>
                <td className="px-3 py-3">
                  <strong className="tabular text-sm font-semibold text-foreground">
                    {formatScore(item.final_score)}
                  </strong>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    置信度 {formatPercent(item.confidence)}
                  </span>
                </td>
                <td className="px-3 py-3 tabular text-foreground">
                  {formatPercent(item.discount_rate)}
                </td>
                <td className="px-3 py-3">
                  <div className="grid gap-1">
                    <span className="text-xs text-foreground">
                      本轮：{item.current_review_outcome}
                    </span>
                    {item.review_required ? (
                      <Badge tone="caution">需要复核</Badge>
                    ) : null}
                  </div>
                </td>
                <td className="px-3 py-3">
                  <div className="grid gap-1">
                    <span className="text-xs text-foreground">
                      有效：{item.effective_assessment_id ?? "暂无"}
                    </span>
                    <Badge tone={statusTone(item.assessment_freshness)}>
                      {item.assessment_freshness}
                    </Badge>
                    {item.stale_reason ? (
                      <span className="text-xs text-muted-foreground">
                        {item.stale_reason}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td className="px-3 py-3">
                  <div className="grid gap-1">
                    <span className="text-xs text-foreground">
                      {item.research_guardrail}
                    </span>
                    {item.risk_flags.length > 0 ? (
                      <span className="text-xs text-muted-foreground">
                        风险 {item.risk_flags.join(" / ")}
                      </span>
                    ) : null}
                  </div>
                </td>
                <td className="px-3 py-3">
                  <div className="grid gap-1">
                    <span className="text-xs text-foreground">
                      {item.data_status}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatDate(item.last_checked_at)}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          本页 {items.length} / page size {pageInfo.page_size}
        </span>
        {pageInfo.has_next_page && pageInfo.next_cursor ? (
          <Button asChild variant="secondary" size="sm">
            <Link
              href={nextHref({
                cursor: pageInfo.next_cursor,
                scopeVersionId,
                universe,
              })}
            >
              下一页
            </Link>
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">已到最后一页</span>
        )}
      </div>
    </div>
  );
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
