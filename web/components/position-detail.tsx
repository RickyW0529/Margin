import {
  Activity,
  AlertCircle,
  Bell,
  ClipboardList,
  History,
  LineChart,
} from "lucide-react";

import type { AlertEvent, OperationHistoryEntry, PositionDetail } from "@/lib/api";

type PositionDetailViewProps = {
  portfolioId: string;
  detail: PositionDetail | null;
  alerts?: AlertEvent[];
  history?: OperationHistoryEntry[];
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

function money(value: number | null | undefined): string {
  return value == null ? "--" : currency.format(value);
}

function ratio(value: number | null | undefined): string {
  return value == null ? "--" : percent.format(value);
}

export function PositionDetailView({
  portfolioId,
  detail,
  alerts = [],
  history = [],
  error,
}: PositionDetailViewProps) {
  if (error) {
    return (
      <main className="workspace-shell">
        <div className="notice-panel" role="alert">
          <AlertCircle aria-hidden="true" size={18} />
          <span>{error}</span>
        </div>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="workspace-shell">
        <div className="notice-panel" role="status">
          <span>数据加载中</span>
        </div>
      </main>
    );
  }

  const timeline = history.length > 0 ? history : tradesToHistory(detail);

  return (
    <main className="workspace-shell detail-shell">
      <section className="workspace-header" aria-labelledby="position-title">
        <div>
          <p className="eyebrow">{portfolioId}</p>
          <h1 id="position-title">{detail.symbol}</h1>
        </div>
        <span className={`badge ${detail.health_status}`}>
          {detail.health_status}
        </span>
      </section>

      <section className="metric-grid detail-metrics" aria-label="持仓指标">
        <Metric label="成本金额" value={money(detail.cost_amount)} />
        <Metric label="成本价" value={money(detail.cost_price)} />
        <Metric label="市值" value={money(detail.market_value)} />
        <Metric label="权重" value={ratio(detail.weight)} />
      </section>

      <section className="workspace-grid">
        <div className="panel">
          <div className="panel-heading">
            <h2>买入逻辑</h2>
            <ClipboardList aria-hidden="true" size={17} />
          </div>
          {detail.thesis ? (
            <div className="thesis-block">
              <p>{detail.thesis.thesis}</p>
              <ConditionList title="持有条件" items={detail.thesis.hold_conditions} />
              <ConditionList
                title="失效条件"
                items={detail.thesis.invalidation_conditions}
              />
            </div>
          ) : (
            <div className="empty-state compact">暂无买入逻辑</div>
          )}
        </div>

        <div className="panel monitoring-panel">
          <div className="panel-heading">
            <h2>持仓监控</h2>
            <Bell aria-hidden="true" size={17} />
          </div>
          {alerts.length === 0 ? (
            <div className="empty-state compact">暂无提醒</div>
          ) : (
            <ul className="alert-list">
              {alerts.map((alert) => (
                <li key={alert.alert_id}>
                  <span className={`badge priority-${alert.severity.toLowerCase()}`}>
                    {alert.severity}
                  </span>
                  <div>
                    <strong>{alert.message}</strong>
                    <span>{alert.rule_name}</span>
                    {alert.evidence_refs.length > 0 ? (
                      <span>证据 {alert.evidence_refs.length}</span>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <aside className="side-rail">
          <div className="panel">
            <div className="panel-heading">
              <h2>盈亏</h2>
              <LineChart aria-hidden="true" size={17} />
            </div>
            <div className="fact-list">
              <span>浮动盈亏</span>
              <strong>{money(detail.unrealized_pnl)}</strong>
              <span>收益率</span>
              <strong>{ratio(detail.unrealized_pnl_pct)}</strong>
              <span>行业</span>
              <strong>{detail.industry ?? "--"}</strong>
            </div>
          </div>
          <div className="panel">
            <div className="panel-heading">
              <h2>操作历史</h2>
              <History aria-hidden="true" size={17} />
            </div>
            {timeline.length === 0 ? (
              <div className="empty-state compact">暂无记录</div>
            ) : (
              <ul className="trade-list">
                {timeline.map((entry) => (
                  <li key={entry.event_id}>
                    <Activity aria-hidden="true" size={15} />
                    <span>{entry.event_type}</span>
                    <strong>{historySummary(entry)}</strong>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ConditionList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <div className="condition-list">
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function tradesToHistory(detail: PositionDetail): OperationHistoryEntry[] {
  return detail.trade_history.map((trade) => ({
    event_id: trade.trade_id,
    position_id: detail.position_id,
    event_type: "trade",
    occurred_at: trade.traded_at,
    summary: `${trade.side} ${trade.quantity.toLocaleString("zh-CN")} @ ${money(trade.price)}`,
    metadata: {},
  }));
}

function historySummary(entry: OperationHistoryEntry): string {
  if (entry.event_type === "alert") {
    return "触发提醒";
  }
  return entry.summary;
}
