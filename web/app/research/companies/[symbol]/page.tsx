/**
 * @fileoverview Company quant + analysis profile page.
 *
 * Displays the full quant screening profile (five factor scores, ranking,
 * status, rejection reasons) and the fourth-layer Analysis Mart metrics and
 * findings for a single security. Data is fetched in parallel from two
 * read-only API endpoints.
 */

import { FactorRadarChart } from "@/components/factor-radar-chart";
import { FindingCard } from "@/components/finding-card";
import { FactorScoreBar } from "@/components/factor-score-bar";
import { MetricRow } from "@/components/metric-row";
import { QuantOverviewCard } from "@/components/quant-overview-card";
import { RejectionReasonPanel } from "@/components/rejection-reason-panel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  fetchCompanyAnalysisProfile,
  fetchCompanyQuantProfile,
  type AnalysisFinding,
  type AnalysisMetric,
  type CompanyAnalysisProfile,
  type CompanyQuantProfile,
} from "@/lib/api";

type CompanyPageProps = {
  params: Promise<{ symbol: string }>;
};

const SCREENING_STATUS_LABELS: Record<string, string> = {
  pass: "通过",
  near_threshold: "接近阈值",
  watchlist: "观察名单",
  reject: "淘汰",
};

const SCREENING_STATUS_TONES: Record<string, "positive" | "accent" | "caution" | "negative" | "muted"> = {
  pass: "positive",
  near_threshold: "accent",
  watchlist: "caution",
  reject: "negative",
};

/** Company quant + analysis profile page with parallel data fetching. */
export default async function CompanyPage({ params }: CompanyPageProps) {
  const { symbol } = await params;
  const securityId = decodeURIComponent(symbol);

  const [quantResult, analysisResult] = await Promise.allSettled([
    fetchCompanyQuantProfile(securityId),
    fetchCompanyAnalysisProfile(securityId),
  ]);

  const quantOk = quantResult.status === "fulfilled";
  const analysisOk = analysisResult.status === "fulfilled";
  const quant = quantOk ? quantResult.value : null;
  const analysis = analysisOk ? analysisResult.value : null;

  if (!quant && !analysis) {
    return (
      <main className="mx-auto max-w-4xl px-8 py-16">
        <ErrorAlert message="无法加载该公司量化与分析数据，请稍后重试。" />
      </main>
    );
  }

  const screeningLabel = quant
    ? (SCREENING_STATUS_LABELS[quant.screening_status] ?? quant.screening_status)
    : null;
  const screeningTone = quant
    ? (SCREENING_STATUS_TONES[quant.screening_status] ?? "muted")
    : "muted";

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-8 py-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Company profile
          </p>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              {securityId}
            </h1>
            {screeningLabel ? (
              <Badge tone={screeningTone}>{screeningLabel}</Badge>
            ) : null}
          </div>
        </div>
        {analysis?.snapshot ? (
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <Badge tone="muted">
              analysis {analysis.snapshot.analysis_snapshot_id.slice(0, 16)}
            </Badge>
          </div>
        ) : null}
      </header>

      {quant ? <QuantOverviewCard profile={quant} /> : null}

      <Tabs defaultValue="factors">
        <TabsList>
          <TabsTrigger value="factors">因子雷达</TabsTrigger>
          <TabsTrigger value="metrics">分析指标</TabsTrigger>
          <TabsTrigger value="findings">关键发现</TabsTrigger>
          <TabsTrigger value="rejection">筛选原因</TabsTrigger>
        </TabsList>

        <TabsContent value="factors">
          <FactorTab quant={quant} />
        </TabsContent>

        <TabsContent value="metrics">
          <MetricsTab analysis={analysis} />
        </TabsContent>

        <TabsContent value="findings">
          <FindingsTab analysis={analysis} />
        </TabsContent>

        <TabsContent value="rejection">
          <RejectionTab quant={quant} />
        </TabsContent>
      </Tabs>

      <LineageFooter quant={quant} analysis={analysis} />
    </main>
  );
}

function FactorTab({ quant }: { quant: CompanyQuantProfile | null }) {
  if (!quant) {
    return <EmptyState message="暂无量化因子数据" />;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>五因子雷达图</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-2">
        <FactorRadarChart factorScores={quant.factor_scores} />
        <div className="grid gap-3">
          {quant.factor_scores.map((item) => (
            <div key={item.factor_key} className="grid gap-1">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-foreground">{item.label}</span>
                <span className="text-xs text-muted-foreground">
                  权重 {(item.weight * 100).toFixed(0)}%
                </span>
              </div>
              <FactorScoreBar
                value={item.score}
                max={100}
              />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function MetricsTab({ analysis }: { analysis: CompanyAnalysisProfile | null }) {
  if (!analysis || analysis.metrics.length === 0) {
    return <EmptyState message="暂无分析指标数据" />;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>分析指标</CardTitle>
        <span className="text-xs text-muted-foreground">
          {analysis.metrics.length} 项指标
        </span>
      </CardHeader>
      <CardContent>
        <div className="grid divide-y divide-border">
          {analysis.metrics.map((metric: AnalysisMetric) => (
            <MetricRow key={metric.metric_id} metric={metric} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function FindingsTab({ analysis }: { analysis: CompanyAnalysisProfile | null }) {
  if (!analysis || analysis.findings.length === 0) {
    return <EmptyState message="暂无关键发现" />;
  }
  return (
    <div className="grid gap-3">
      {analysis.findings.map((finding: AnalysisFinding) => (
        <FindingCard key={finding.finding_id} finding={finding} />
      ))}
    </div>
  );
}

function RejectionTab({ quant }: { quant: CompanyQuantProfile | null }) {
  if (!quant) {
    return <EmptyState message="暂无筛选原因数据" />;
  }
  return (
    <RejectionReasonPanel
      screeningStatus={quant.screening_status}
      reviewRequired={quant.review_required}
      reviewReasons={quant.review_reasons}
      riskFlags={quant.risk_flags}
      reasonSummary={quant.reason_summary}
    />
  );
}

function LineageFooter({
  quant,
  analysis,
}: {
  quant: CompanyQuantProfile | null;
  analysis: CompanyAnalysisProfile | null;
}) {
  if (!quant && !analysis?.snapshot) {
    return null;
  }
  return (
    <Card>
      <CardContent className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        {quant ? (
          <>
            <span>quant_run {quant.quant_run_id.slice(0, 20)}</span>
            <span>result {quant.result_id.slice(0, 20)}</span>
          </>
        ) : null}
        {analysis?.snapshot ? (
          <>
            <span>
              analysis {analysis.snapshot.analysis_snapshot_id.slice(0, 20)}
            </span>
            <span>version {analysis.snapshot.analysis_version}</span>
            <span>links {analysis.evidence_link_count}</span>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ErrorAlert({ message }: { message: string }) {
  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
      role="alert"
    >
      {message}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <p className="text-sm text-muted-foreground">{message}</p>
      </CardContent>
    </Card>
  );
}
