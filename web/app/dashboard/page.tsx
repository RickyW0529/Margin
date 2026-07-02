/**
 * @fileoverview User-facing recommendation dashboard.
 */

import Link from "next/link";

import { DashboardRefreshControl } from "@/components/dashboard-refresh-control";
import { Badge } from "@/components/ui/badge";
import {
  fetchResearchCandidates,
  type ResearchCandidateListItemV2,
} from "@/lib/api";
import { cn, formatDate, formatScore } from "@/lib/utils";

export const dynamic = "force-dynamic";

/** Recommendation dashboard with cards, evidence summaries, and compact visuals. */
export default async function RecommendationDashboardPage() {
  const candidates = await fetchResearchCandidates({
    limit: 20,
    scope_version_id: "scope-current",
    universe: "ALL_A",
  }).catch(() => null);
  const items = candidates?.items ?? [];
  const reviewCount = items.filter((item) => item.review_required).length;
  const averageConfidence =
    items.length === 0
      ? null
      : items.reduce((total, item) => total + (item.confidence ?? 0), 0) /
        items.length;

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8 md:px-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">
            {formatDate(candidates?.as_of)}
          </p>
          <h1 className="mt-1 text-4xl font-semibold tracking-tight text-foreground">
            今日推荐
          </h1>
        </div>
        <div className="grid justify-items-start gap-3 md:justify-items-end">
          <DashboardRefreshControl />
          <div className="flex flex-wrap gap-2 md:justify-end">
            <MetricPill label="推荐" value={`${items.length}`} />
            <MetricPill label="平均置信度" value={formatPercentOne(averageConfidence)} />
            <MetricPill label="需复核" value={`${reviewCount}`} />
          </div>
        </div>
      </header>

      <section className="grid gap-3">
        {items.length > 0 ? (
          items.map((item, index) => (
            <RecommendationCard
              key={item.item_id}
              item={item}
              rank={index + 1}
            />
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-border bg-card px-4 py-10 text-center text-sm text-muted-foreground">
            今日暂无推荐。
          </div>
        )}
      </section>
    </main>
  );
}

function RecommendationCard({
  item,
  rank,
}: {
  item: ResearchCandidateListItemV2;
  rank: number;
}) {
  const reasons = buildReasons(item);
  const detailHref = `/dashboard/items/${encodeURIComponent(item.item_id)}`;
  return (
    <article
      className={cn(
        "grid gap-4 rounded-lg border bg-card p-4 shadow-sm transition-colors md:grid-cols-[auto_minmax(0,1fr)_minmax(220px,260px)]",
        "border-border",
      )}
    >
      <div className="grid size-10 place-items-center rounded-md bg-muted text-sm font-semibold text-foreground">
        {rank}
      </div>
      <div className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Link
              href={detailHref}
              className="text-lg font-semibold text-foreground no-underline hover:text-accent"
            >
              {item.name}
            </Link>
            <p className="text-sm text-muted-foreground">{item.symbol}</p>
          </div>
          <Badge tone={statusTone(item.screening_status)}>
            {statusLabel(item.screening_status)}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          {reasons.map((reason) => (
            <span
              key={reason}
              className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
            >
              {reason}
            </span>
          ))}
        </div>
        {item.risk_flags.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            风险：{item.risk_flags.slice(0, 2).join(" / ")}
          </p>
        ) : null}
      </div>
      <div className="grid gap-2 rounded-md bg-muted/40 p-3 md:self-start">
        <MetricLine label="置信度" value={formatPercentOne(item.confidence)} />
        <MetricLine label="量化评分" value={formatScore(item.final_score)} />
        <MetricLine label="估值折价" value={formatPercentOne(item.discount_rate)} />
        <Link
          href={detailHref}
          className="mt-1 text-xs font-medium text-accent no-underline hover:underline"
        >
          查看详情
        </Link>
      </div>
    </article>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <strong className="ml-2 text-sm text-foreground">{value}</strong>
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-sm">
      <span className="text-muted-foreground">{label} </span>
      <strong className="text-foreground">{value}</strong>
    </div>
  );
}

function buildReasons(item: ResearchCandidateListItemV2): string[] {
  const reasons = [item.data_status === "complete" ? "数据完整" : "数据待补齐"];
  if (item.review_required) {
    reasons.push("需复核");
  }
  if (item.current_review_outcome) {
    reasons.push(item.current_review_outcome);
  }
  return reasons.slice(0, 4);
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pass: "通过",
    near_threshold: "接近阈值",
    watchlist: "观察",
    reject: "淘汰",
  };
  return labels[status] ?? status;
}

function statusTone(status: string): "positive" | "accent" | "caution" | "negative" | "muted" {
  if (status === "pass") {
    return "positive";
  }
  if (status === "near_threshold") {
    return "accent";
  }
  if (status === "watchlist") {
    return "caution";
  }
  if (status === "reject") {
    return "negative";
  }
  return "muted";
}

function formatPercentOne(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
    style: "percent",
  }).format(value);
}
