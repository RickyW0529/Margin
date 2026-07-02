/**
 * @fileoverview Recommendation detail view with quant visuals and evidence.
 */

import { CurrentVsEffectivePanel } from "@/components/current-vs-effective-panel";
import { EvidenceLocatorList } from "@/components/evidence-locator-list";
import { FactorScoreBar } from "@/components/factor-score-bar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ResearchItemDetailV2 } from "@/lib/api";
import { formatScore } from "@/lib/utils";

type RecommendationDetailProps = {
  detail: ResearchItemDetailV2;
};

/** Renders a focused detail page for one dashboard recommendation. */
export function RecommendationDetail({ detail }: RecommendationDetailProps) {
  const item = detail.item;
  const factorEntries = Object.entries(detail.factors).filter(
    ([, value]) => typeof value === "number",
  );

  return (
    <section className="grid gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">推荐详情</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            {item.name}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{item.security_id}</p>
        </div>
        <Badge tone={statusTone(item.screening_status)}>
          {statusLabel(item.screening_status)}
        </Badge>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle>研究结论</CardTitle>
              <span className="text-xs text-muted-foreground">
                置信度 {formatPercentOne(item.confidence)}
              </span>
            </CardHeader>
            <CardContent className="grid gap-3">
              <p className="text-sm leading-relaxed text-foreground">
                {safeText(detail.thesis.statement) ?? "暂无结论"}
              </p>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>scope {item.scope_version_id}</span>
                <span>snapshot {detail.versions.snapshot_id ?? "--"}</span>
              </div>
            </CardContent>
          </Card>

          <CurrentVsEffectivePanel
            currentReview={detail.current_review}
            effectiveAssessment={detail.effective_assessment}
          />
          <EvidenceLocatorList evidence={detail.evidence} />
        </div>

        <aside className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>量化可视化</CardTitle>
              <Badge tone="muted">{item.research_guardrail}</Badge>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid grid-cols-2 gap-3">
                <MetricTile label="筛选状态" value={statusLabel(item.screening_status)} />
                <MetricTile label="数据状态" value={item.data_status} />
                <MetricTile label="最终分数" value={formatScore(item.final_score)} />
                <MetricTile label="置信度" value={formatPercentOne(item.confidence)} />
              </div>
              {factorEntries.length > 0 ? (
                <div className="grid gap-3 border-t border-border pt-3">
                  {factorEntries.map(([key, value]) => (
                    <FactorScoreBar key={key} label={key} value={value as number} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">暂无因子快照。</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>风险与复核</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              {item.risk_flags.length > 0 ? (
                item.risk_flags.map((flag) => (
                  <Badge key={flag} tone="caution">
                    {flag}
                  </Badge>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">暂无明显风险标记。</p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </section>
  );
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 rounded-md border border-border bg-muted/40 px-3 py-2.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <strong className="text-sm text-foreground">{value}</strong>
    </div>
  );
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

function safeText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
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
