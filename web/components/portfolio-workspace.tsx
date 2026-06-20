/**
 * @fileoverview Workspace component that renders a portfolio dashboard,
 * positions table, exposures, and upcoming events.
 */

import {
  AlertTriangle,
  ArrowUpRight,
  CalendarClock,
  CircleDollarSign,
  PieChart,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import Link from "next/link";

import type { PortfolioDashboard, Position } from "@/lib/api";

/** Props for the PortfolioWorkspace component. */
type PortfolioWorkspaceProps = {
  /** Portfolio dashboard data, or null while loading. */
  dashboard: PortfolioDashboard | null;
  /** Array of positions to render in the positions table. */
  positions: Position[];
  /** Error message to display, or null when no error. */
  error: string | null;
};

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 0,
});

const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 1,
});

/**
 * Formats a monetary value as a localized CNY string.
 *
 * @param value Monetary value, or null/undefined if unavailable.
 * @returns Formatted currency or "--".
 */
function money(value: number | null | undefined): string {
  return value == null ? "--" : currency.format(value);
}

/**
 * Formats a fractional ratio as a localized percentage string.
 *
 * @param value Ratio value, or null/undefined if unavailable.
 * @returns Formatted percentage or "--".
 */
function ratio(value: number | null | undefined): string {
  return value == null ? "--" : percent.format(value);
}

/**
 * Formats a signed monetary value with an explicit plus or minus prefix.
 *
 * @param value Monetary value, or null/undefined if unavailable.
 * @returns Signed formatted currency or "--".
 */
function signedMoney(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${currency.format(value)}`;
}

/**
 * Determines the visual tone for a signed metric value.
 *
 * @param value Signed metric value.
 * @returns Visual tone identifier.
 */
function metricTone(
  value: number | null | undefined,
): "neutral" | "positive" | "negative" {
  if (value == null || value === 0) {
    return "neutral";
  }
  return value > 0 ? "positive" : "negative";
}

/**
 * Renders the portfolio workspace with metrics, positions, and risk panels.
 *
 * @param dashboard Portfolio dashboard data.
 * @param positions Portfolio positions.
 * @param error Error message.
 * @returns The portfolio workspace or a loading/error state.
 */
export function PortfolioWorkspace({
  dashboard,
  positions,
  error,
}: PortfolioWorkspaceProps) {
  if (error) {
    return (
      <main className="workspace-shell">
        <div className="notice-panel" role="alert">
          <AlertTriangle aria-hidden="true" size={18} />
          <span>{error}</span>
        </div>
      </main>
    );
  }

  if (!dashboard) {
    return (
      <main className="workspace-shell">
        <div className="notice-panel" role="status">
          <span>数据加载中</span>
        </div>
      </main>
    );
  }

  const { portfolio, overview } = dashboard;

  return (
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="portfolio-title">
        <div>
          <p className="eyebrow">Portfolio</p>
          <h1 id="portfolio-title">{portfolio.name}</h1>
        </div>
        <div className="status-strip" aria-label="组合状态">
          <span>{overview.position_count} 个持仓</span>
          <span>{overview.high_risk_count} 个高风险</span>
        </div>
      </section>

      <section className="metric-grid" aria-label="组合指标">
        <MetricTile
          icon={<CircleDollarSign aria-hidden="true" size={18} />}
          label="总资产"
          value={money(overview.total_assets)}
        />
        <MetricTile
          icon={<Wallet aria-hidden="true" size={18} />}
          label="现金"
          value={money(overview.cash)}
        />
        <MetricTile
          icon={<PieChart aria-hidden="true" size={18} />}
          label="市值"
          value={money(overview.market_value)}
        />
        <MetricTile
          icon={<ArrowUpRight aria-hidden="true" size={18} />}
          label="累计盈亏"
          value={signedMoney(overview.cumulative_pnl)}
          tone={metricTone(overview.cumulative_pnl)}
        />
      </section>

      <section className="workspace-grid">
        <div className="panel positions-panel">
          <div className="panel-heading">
            <h2>持仓</h2>
            <span>{positions.length} 条持仓</span>
          </div>
          {positions.length === 0 ? (
            <div className="empty-state">暂无持仓</div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>数量</th>
                    <th>成本</th>
                    <th>市值</th>
                    <th>盈亏</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((position) => (
                    <tr key={position.position_id}>
                      <td className="symbol-cell">
                        <Link
                          className="table-link"
                          href={{
                            pathname: `/positions/${position.position_id}`,
                            query: { portfolioId: position.portfolio_id },
                          }}
                        >
                          {position.symbol}
                        </Link>
                      </td>
                      <td>{position.quantity.toLocaleString("zh-CN")}</td>
                      <td>{money(position.cost_amount)}</td>
                      <td>{money(position.market_value)}</td>
                      <td className={metricTone(position.unrealized_pnl)}>
                        {signedMoney(position.unrealized_pnl)}
                      </td>
                      <td>
                        <span className={`badge ${position.health_status}`}>
                          {position.health_status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <aside className="side-rail" aria-label="风险和事件">
          <ExposurePanel title="行业暴露" values={overview.industry_exposure} />
          <ExposurePanel title="风格暴露" values={overview.style_exposure} />
          <div className="panel">
            <div className="panel-heading">
              <h2>即将发生</h2>
              <CalendarClock aria-hidden="true" size={17} />
            </div>
            {overview.upcoming_events.length === 0 ? (
              <div className="empty-state compact">暂无事件</div>
            ) : (
              <ul className="event-list">
                {overview.upcoming_events.map((event, index) => (
                  <li key={`${event.symbol ?? "event"}-${index}`}>
                    <span>{String(event.symbol ?? "未命名")} 事件</span>
                    <strong>{String(event.days_until ?? "--")} 天</strong>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="panel risk-panel">
            <div className="risk-line">
              <ShieldAlert aria-hidden="true" size={17} />
              <span>波动率 {ratio(overview.portfolio_volatility)}</span>
              <span>回撤 {ratio(overview.max_drawdown)}</span>
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}

/**
 * Renders a single metric tile with an icon, label, value, and optional tone.
 *
 * @param icon Icon element.
 * @param label Metric label.
 * @param value Formatted metric value.
 * @param tone Visual tone applied to the value.
 * @returns The metric tile element.
 */
function MetricTile({
  icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative";
}) {
  return (
    <div className="metric-tile">
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

/**
 * Renders an exposure breakdown panel with progress meters.
 *
 * @param title Panel heading.
 * @param values Map of exposure names to fractional values.
 * @returns The exposure panel element.
 */
function ExposurePanel({
  title,
  values,
}: {
  title: string;
  values: Record<string, number>;
}) {
  const entries = Object.entries(values);

  return (
    <div className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
      </div>
      {entries.length === 0 ? (
        <div className="empty-state compact">暂无数据</div>
      ) : (
        <ul className="exposure-list">
          {entries.map(([name, value]) => (
            <li key={name}>
              <div>
                <span>{name}</span>
                <strong>{ratio(value)}</strong>
              </div>
              <meter min={0} max={1} value={value} aria-label={`${name} ${ratio(value)}`} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
