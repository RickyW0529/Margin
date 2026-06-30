/**
 * @fileoverview Research item detail page.
 * Displays evidence, valuation, audit trace, report, and feedback for a research item.
 */

import { CurrentVsEffectivePanel } from "@/components/current-vs-effective-panel";
import { EvidenceLocatorList } from "@/components/evidence-locator-list";
import { FactorScoreBar } from "@/components/factor-score-bar";
import { ResearchFeedbackForm } from "@/components/research-feedback-form";
import { ResearchStatusBadge } from "@/components/research-status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchResearchItemDetailV2,
  type ResearchItemDetailV2,
} from "@/lib/api";
import { formatNumber, formatPercent } from "@/lib/utils";
import Link from "next/link";

import { createResearchFeedbackAction } from "./actions";

type ResearchItemPageProps = {
  params: Promise<{ itemId: string }>;
};

/** Research item detail page that loads item data and binds the feedback action. */
export default async function ResearchItemPage({
  params,
}: ResearchItemPageProps) {
  const { itemId } = await params;
  let detail: ResearchItemDetailV2 | null = null;
  let error: string | null = null;

  const detailResult = await Promise.allSettled([
    fetchResearchItemDetailV2(itemId),
  ]);

  if (detailResult[0].status === "fulfilled") {
    detail = detailResult[0].value;
  } else {
    error = "研究详情暂时不可用";
  }

  const item = detail?.item;
  const factors = detail?.factors ?? {};
  const factorEntries = Object.entries(factors).filter(
    ([, value]) => typeof value === "number",
  );

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-8 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Research Item
          </p>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              {item?.symbol ?? itemId}
            </h1>
            {item?.name ? (
              <span className="text-sm text-muted-foreground">
                {item.name}
              </span>
            ) : null}
          </div>
        </div>
        {item ? <ResearchStatusBadge status={item.screening_status} /> : null}
        {item?.security_id ? (
          <Link
            href={`/research/companies/${encodeURIComponent(item.security_id)}`}
            className="text-xs text-muted-foreground no-underline hover:text-accent hover:underline"
          >
            查看量化指标 →
          </Link>
        ) : null}
      </header>

      {error ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          {error}
        </div>
      ) : (
        <div className="grid gap-6">
          {/* 研究结论 */}
          <Card>
            <CardHeader>
              <CardTitle>研究结论</CardTitle>
              <span className="text-xs text-muted-foreground">
                {item?.confidence == null
                  ? "--"
                  : `${(item.confidence * 100).toFixed(0)}%`}
              </span>
            </CardHeader>
            <CardContent className="grid gap-3">
              <p className="text-sm leading-relaxed text-foreground">
                {safeText(detail?.thesis.statement) ?? "暂无结论"}
              </p>
              <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span>run {detail?.versions.run_id ?? "--"}</span>
                <span>snapshot {detail?.versions.snapshot_id ?? "--"}</span>
                <span>
                  workflow {detail?.versions.workflow_run_id ?? "--"}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* 量化与风险快照 */}
          <Card>
            <CardHeader>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-accent">
                  Quant snapshot
                </p>
                <CardTitle className="mt-1">量化与风险快照</CardTitle>
              </div>
              <Badge tone="muted">
                {item?.research_guardrail ?? "--"}
              </Badge>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Stat
                  label="筛选状态"
                  value={item?.screening_status ?? "--"}
                />
                <Stat label="数据状态" value={item?.data_status ?? "--"} />
                <Stat
                  label="最终分数"
                  value={formatNumber(item?.final_score)}
                />
                <Stat
                  label="折价率"
                  value={formatPercent(item?.discount_rate)}
                />
              </div>
              {item?.risk_flags && item.risk_flags.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {item.risk_flags.map((flag) => (
                    <Badge key={flag} tone="caution">
                      {flag}
                    </Badge>
                  ))}
                </div>
              ) : null}
              {factorEntries.length > 0 ? (
                <div className="grid gap-3 border-t border-border pt-3">
                  {factorEntries.map(([key, value]) => (
                    <FactorScoreBar
                      key={key}
                      label={key}
                      value={value as number}
                    />
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <CurrentVsEffectivePanel
            currentReview={detail?.current_review ?? null}
            effectiveAssessment={detail?.effective_assessment ?? null}
          />
          <EvidenceLocatorList evidence={detail?.evidence ?? []} />
          <ResearchFeedbackForm
            action={createResearchFeedbackAction.bind(null, itemId)}
          />
        </div>
      )}
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 rounded-md border border-border bg-muted/40 px-3 py-2.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <strong className="tabular text-sm font-semibold text-foreground">
        {value}
      </strong>
    </div>
  );
}

function safeText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}
