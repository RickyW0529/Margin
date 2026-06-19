import Link from "next/link";

import { ProviderStatusPanel } from "@/components/provider-status-panel";
import {
  fetchPortfolioDashboard,
  fetchProviderStatus,
  fetchResearchHome,
  fetchResearchRuns,
  type PortfolioDashboard,
  type ProviderStatus,
  type ResearchHomeSummary,
  type ResearchRun,
} from "@/lib/api";

export const dynamic = "force-dynamic";

const DEFAULT_PORTFOLIO_ID = process.env.MARGIN_DEFAULT_PORTFOLIO_ID ?? "demo";

export default async function HomePage() {
  const [dashboardResult, researchResult, runsResult, providersResult] =
    await Promise.allSettled([
      fetchPortfolioDashboard(DEFAULT_PORTFOLIO_ID),
      fetchResearchHome(),
      fetchResearchRuns(),
      fetchProviderStatus(),
    ]);

  const dashboard = fulfilledValue<PortfolioDashboard>(dashboardResult);
  const research = fulfilledValue<ResearchHomeSummary>(researchResult);
  const runs = fulfilledValue<ResearchRun[]>(runsResult) ?? [];
  const providers = fulfilledValue<ProviderStatus[]>(providersResult) ?? [];
  const errors = [
    dashboardResult,
    researchResult,
    runsResult,
    providersResult,
  ].filter((result) => result.status === "rejected").length;

  return (
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="home-title">
        <div>
          <p className="eyebrow">Margin</p>
          <h1 id="home-title">Margin 工作台</h1>
        </div>
        <div className="status-strip">
          <span>默认组合 {DEFAULT_PORTFOLIO_ID}</span>
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
          label="组合"
          value={dashboard?.portfolio.name ?? "不可用"}
          helper={`${dashboard?.overview.position_count ?? 0} 个持仓`}
        />
        <Metric
          label="总资产"
          value={money(dashboard?.overview.total_assets)}
          helper={`现金 ${money(dashboard?.overview.cash)}`}
        />
        <Metric
          label="研究运行"
          value={`${runs.length}`}
          helper={research?.run_status ?? "暂无最新运行"}
        />
        <Metric
          label="高风险候选"
          value={`${research?.high_priority_risks.length ?? 0}`}
          helper={`待复盘 ${research?.position_reviews.length ?? 0}`}
        />
      </section>

      <section className="workspace-grid">
        <div className="panel">
          <div className="panel-heading">
            <h2>核心工作流</h2>
            <span>真实 API-backed</span>
          </div>
          <div className="action-grid">
            <Link
              className="primary-button link-button"
              href={`/portfolios/${DEFAULT_PORTFOLIO_ID}`}
            >
              打开组合看板
            </Link>
            <Link className="primary-button link-button" href="/research">
              进入研究面板
            </Link>
            {research?.run_id ? (
              <Link
                className="secondary-link"
                href={`/research/runs/${research.run_id}`}
              >
                查看最新研究运行
              </Link>
            ) : (
              <span className="helper-text">暂无最新研究运行</span>
            )}
          </div>
        </div>
        <ProviderStatusPanel providers={providers} />
      </section>
    </main>
  );
}

function fulfilledValue<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === "fulfilled" ? result.value : null;
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

function money(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(value);
}
