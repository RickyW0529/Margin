/**
 * @fileoverview Home page for the Margin workspace.
 * Aggregates research runs, candidate status, and provider health.
 */

import Link from "next/link";

import { ProviderStatusPanel } from "@/components/provider-status-panel";
import {
  fetchProviderConfigs,
  fetchProviderStatus,
  fetchResearchCandidates,
  type ProviderConfigSummary,
  type ProviderStatus,
  type ResearchCandidateListResponse,
} from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Workspace home page that fetches summary data from multiple APIs in parallel.
 * @returns The rendered home page with metrics, navigation, and provider status.
 */
export default async function HomePage() {
  const [
    candidatesResult,
    providersResult,
    providerConfigsResult,
  ] =
    await Promise.allSettled([
      fetchResearchCandidates({
        limit: 8,
        scope_version_id: "scope-current",
        universe: "ALL_A",
      }),
      fetchProviderStatus(),
      fetchProviderConfigs(),
    ]);

  const candidates = fulfilledValue<ResearchCandidateListResponse>(candidatesResult);
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
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="home-title">
        <div>
          <p className="eyebrow">Margin</p>
          <h1 id="home-title">Margin 工作台</h1>
        </div>
        <div className="status-strip">
          <span>公司池估值发现</span>
          <span>{errors === 0 ? "API 已连接" : `${errors} 个接口异常`}</span>
        </div>
      </section>

      {errors > 0 ? (
        <div className="notice-panel" role="alert">
          <span>部分后端数据暂时不可用，页面已保留可用的真实接口结果。</span>
        </div>
      ) : null}

      <section className="metric-grid" aria-label="产品入口指标">
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

      <section className="workspace-grid">
        <div className="panel">
          <div className="panel-heading">
            <h2>核心工作流</h2>
            <span>真实 API-backed</span>
          </div>
          <div className="action-grid">
            <Link className="primary-button link-button" href="/research">
              进入研究面板
            </Link>
            <Link className="secondary-link" href="/settings/scope">
              配置研究作用域
            </Link>
            <span className="helper-text">
              运行进度从估值发现 run 页面查看，候选结果从 Dashboard projection 查看。
            </span>
          </div>
        </div>
        <ProviderStatusPanel providers={providers} />
      </section>
      {providerConfigs.length === 0 ? (
        <div className="notice-panel">
          <span>尚未激活版本化 Provider 配置。</span>
          <Link className="secondary-link" href="/settings/providers">
            前往设置
          </Link>
        </div>
      ) : null}
    </main>
  );
}

function fulfilledValue<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === "fulfilled" ? result.value : null;
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
    <div className="metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
      <span>{helper}</span>
    </div>
  );
}
