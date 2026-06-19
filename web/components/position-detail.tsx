import {
  Activity,
  AlertCircle,
  Bell,
  ClipboardList,
  History,
  LineChart,
} from "lucide-react";

import type { AlertEvent, OperationHistoryEntry, PositionDetail } from "@/lib/api";

type FormAction = (formData: FormData) => void | Promise<void>;

type PositionDetailViewProps = {
  portfolioId: string;
  evaluateAction: FormAction;
  reviewAction: FormAction;
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
  evaluateAction,
  reviewAction,
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
          <MonitoringEvaluateForm
            action={evaluateAction}
            portfolioId={portfolioId}
            detail={detail}
          />
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
          <ReviewForm
            action={reviewAction}
            portfolioId={portfolioId}
            alerts={alerts}
          />
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

function MonitoringEvaluateForm({
  action,
  portfolioId,
  detail,
}: {
  action: FormAction;
  portfolioId: string;
  detail: PositionDetail;
}) {
  return (
    <form action={action} className="action-form inline-form">
      <input name="portfolio_id" type="hidden" value={portfolioId} />
      <div className="form-grid">
        <label className="form-field">
          <span>当前价格</span>
          <input
            name="current_price"
            type="number"
            step="0.0001"
            defaultValue={detail.current_price ?? ""}
            placeholder="留空则使用后端价格"
          />
        </label>
        <label className="form-field">
          <span>模型排名变化</span>
          <input
            name="model_rank_delta"
            type="number"
            step="0.01"
            placeholder="-0.3"
          />
        </label>
        <label className="form-field">
          <span>行业暴露</span>
          <input
            name="industry_exposure"
            type="number"
            step="0.01"
            placeholder="0.4"
          />
        </label>
      </div>
      <label className="form-field">
        <span>证据 ID</span>
        <input
          name="evidence_refs"
          placeholder="ev_1, ev_2；提交后写入 alert evidence_refs"
        />
      </label>
      <label className="checkbox-field">
        <input name="strategy_failure" type="checkbox" />
        <span>标记策略失效</span>
      </label>
      <button className="primary-button" type="submit">
        重新评估持仓监控
      </button>
    </form>
  );
}

function ReviewForm({
  action,
  portfolioId,
  alerts,
}: {
  action: FormAction;
  portfolioId: string;
  alerts: AlertEvent[];
}) {
  return (
    <section className="panel" aria-labelledby="review-form-title">
      <div className="panel-heading">
        <h2 id="review-form-title">复盘记录</h2>
        <span>POST /reviews</span>
      </div>
      <form action={action} className="action-form">
        <input name="portfolio_id" type="hidden" value={portfolioId} />
        <label className="form-field">
          <span>关联提醒</span>
          <select name="alert_id" defaultValue={alerts[0]?.alert_id ?? ""}>
            <option value="">不绑定提醒</option>
            {alerts.map((alert) => (
              <option key={alert.alert_id} value={alert.alert_id}>
                {alert.severity} · {alert.rule_name}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>复盘决策</span>
          <select name="decision" defaultValue="watch">
            <option value="hold">继续持有</option>
            <option value="reduce">降低仓位</option>
            <option value="exit">退出</option>
            <option value="watch">继续观察</option>
            <option value="ignore">忽略</option>
          </select>
        </label>
        <label className="form-field">
          <span>复盘理由</span>
          <textarea name="rationale" required rows={3} />
        </label>
        <button className="primary-button" type="submit">
          记录复盘
        </button>
      </form>
    </section>
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
