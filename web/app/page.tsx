/**
 * @fileoverview Home page for the Margin workspace.
 * Aggregates research candidates, provider health, and the recommended
 * operational workflow into a single product overview.
 */

import Link from "next/link";
import { AlertTriangle, ArrowRight, RefreshCw } from "lucide-react";

import { ProviderStatusPanel } from "@/components/provider-status-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchProviderConfigs,
  fetchProviderStatus,
  fetchResearchCandidates,
  type ProviderConfigSummary,
  type ProviderStatus,
  type ResearchCandidateListResponse,
} from "@/lib/api";
import { formatDate, formatScore } from "@/lib/utils";

export const dynamic = "force-dynamic";

/** Workspace home page that fetches summary data from multiple APIs in parallel. */
export default async function HomePage() {
  const [candidatesResult, providersResult, providerConfigsResult] =
    await Promise.allSettled([
      fetchResearchCandidates({
        limit: 8,
        scope_version_id: "scope-current",
        universe: "ALL_A",
      }),
      fetchProviderStatus(),
      fetchProviderConfigs(),
    ]);

  const candidates =
    fulfilledValue<ResearchCandidateListResponse>(candidatesResult);
  const providers = fulfilledValue<ProviderStatus[]>(providersResult) ?? [];
  const providerConfigs =
    fulfilledValue<ProviderConfigSummary[]>(providerConfigsResult) ?? [];
  const errors = [
    candidatesResult,
    providersResult,
    providerConfigsResult,
  ].filter((result) => result.status === "rejected").length;
  const candidateItems = candidates?.items ?? [];
  const reviewRequiredCount = candidateItems.filter(
    (item) => item.review_required,
  ).length;
  const riskFlagCount = candidateItems.filter(
    (item) => item.risk_flags.length > 0,
  ).length;

  return (
    <main className="mx-auto max-w-5xl space-y-9 px-10 py-10">
      {/* Hero */}
      <section>
        <p className="mb-3 text-sm text-muted-foreground">
          个人投资研究系统 · 沪深 300 / 中证 500 / 全 A
        </p>
        <h1 className="max-w-2xl text-4xl font-semibold leading-tight tracking-tight text-foreground">
          研究工作台
        </h1>
        <p className="mt-4 max-w-2xl leading-relaxed text-muted-foreground">
          Margin 持续维护可选公司池的内在价值研究账本：回答「这家公司基于当前可用证据本应该值多少」，而非预测明日价格。量化层先排除明显不符合策略的公司，AI 只在量化通过或信息变化时复核。
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button asChild>
            <Link href="/research">
              打开研究候选 <ArrowRight className="size-4" />
            </Link>
          </Button>
          <Button asChild variant="secondary">
            <Link href="/settings/providers">
              <RefreshCw className="size-4" /> 同步数据 / 重试同步
            </Link>
          </Button>
        </div>
      </section>

      {errors > 0 ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          <AlertTriangle className="size-4 shrink-0" />
          部分后端数据暂时不可用，页面已保留可用的真实接口结果。
        </div>
      ) : null}

      {/* Metrics */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric
          label="今日候选"
          value={`${candidateItems.length}`}
          helper="v0.2 candidate BFF"
        />
        <Metric
          label="最新刷新"
          value={candidates ? formatDate(candidates.as_of) : "暂无"}
          helper={candidates?.scope_version_id ?? "scope-current"}
        />
        <Metric
          label="需复核"
          value={`${reviewRequiredCount}`}
          helper="AI/人工复核队列"
        />
        <Metric
          label="高风险候选"
          value={`${riskFlagCount}`}
          helper="需要进一步阅读证据"
        />
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-6">
          {/* Candidate snapshot */}
          <Card>
            <CardHeader>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-accent">
                  Candidate snapshot
                </p>
                <CardTitle className="mt-1">最新候选快照</CardTitle>
              </div>
              <span className="text-xs text-muted-foreground">
                {candidateItems.length} items
              </span>
            </CardHeader>
            <CardContent className="grid gap-2">
              {candidateItems.length > 0 ? (
                candidateItems.slice(0, 5).map((item) => (
                  <Link
                    key={item.item_id}
                    href={`/research/items/${item.item_id}`}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-border bg-muted/50 px-3 py-2.5 no-underline transition-colors hover:bg-card"
                  >
                    <span className="grid gap-0.5">
                      <span className="text-sm font-semibold text-foreground">
                        {item.symbol}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {item.name}
                      </span>
                    </span>
                    <span className="grid justify-items-end gap-0.5">
                      <span className="text-xs text-muted-foreground">
                        {item.screening_status}
                      </span>
                      <span className="tabular text-sm font-semibold text-foreground">
                        {formatScore(item.final_score)}
                      </span>
                    </span>
                  </Link>
                ))
              ) : (
                <div className="grid place-items-center rounded-md border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
                  当前筛选暂无候选，先确认数据同步和 Provider 状态。
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>操作顺序</CardTitle>
              <span className="text-xs text-muted-foreground">推荐路径</span>
            </CardHeader>
            <CardContent className="grid gap-2.5">
              <Step
                n="1"
                title="Provider"
                desc="先确认 LLM、Embedding、Tushare、Tavily 是否可用。"
              />
              <Step
                n="2"
                title="Scope"
                desc="选择公司池和指标视图，不改变底层全量仓库。"
              />
              <Step
                n="3"
                title="Research"
                desc="候选页触发刷新，结果落到 current/effective 结论。"
              />
            </CardContent>
          </Card>
          <ProviderStatusPanel providers={providers} />
        </aside>
      </div>

      {providerConfigs.length === 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
          <span className="text-sm text-muted-foreground">
            尚未激活版本化 Provider 配置。
          </span>
          <Button asChild variant="secondary" size="sm">
            <Link href="/settings/providers">前往设置</Link>
          </Button>
        </div>
      ) : null}
    </main>
  );
}

function Metric({
  label,
  value,
  helper,
}: {
  label: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="grid gap-2 rounded-lg border border-border bg-card p-4 shadow-sm">
      <span className="text-xs font-medium text-muted-foreground">
        {label}
      </span>
      <strong className="text-2xl font-semibold tracking-tight text-foreground">
        {value}
      </strong>
      <span className="text-xs text-muted-foreground">{helper}</span>
    </div>
  );
}

function Step({ n, title, desc }: { n: string; title: string; desc: string }) {
  return (
    <div className="grid gap-1 rounded-md border border-border bg-muted/40 p-3">
      <strong className="text-sm text-foreground">
        {n}. {title}
      </strong>
      <span className="text-xs leading-relaxed text-muted-foreground">
        {desc}
      </span>
    </div>
  );
}

function fulfilledValue<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === "fulfilled" ? result.value : null;
}
