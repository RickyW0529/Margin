export type Portfolio = {
  portfolio_id: string;
  user_id: string;
  name: string;
  cash: number;
  created_at: string;
};

export type PortfolioOverview = {
  portfolio_id: string;
  portfolio_name: string;
  total_assets: number;
  cash: number;
  market_value: number;
  today_pnl: number | null;
  cumulative_pnl: number;
  portfolio_volatility: number | null;
  max_drawdown: number | null;
  industry_exposure: Record<string, number>;
  style_exposure: Record<string, number>;
  high_risk_count: number;
  upcoming_events: Array<Record<string, string | number | null>>;
  position_count: number;
  updated_at: string;
};

export type PortfolioDashboard = {
  portfolio: Portfolio;
  overview: PortfolioOverview;
};

export type PositionThesis = {
  thesis_id: string;
  position_id: string;
  thesis: string;
  entry_conditions: string[];
  hold_conditions: string[];
  invalidation_conditions: string[];
  target_horizon: number[];
  next_review_at: string | null;
  status: string;
  version: number;
  created_at: string;
};

export type Position = {
  position_id: string;
  portfolio_id: string;
  symbol: string;
  quantity: number;
  cost_price: number;
  cost_amount: number;
  current_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  industry: string | null;
  health_status: string;
  thesis: PositionThesis | null;
  updated_at: string;
};

export type TradeHistoryItem = {
  trade_id: string;
  side: string;
  quantity: number;
  price: number;
  amount: number;
  traded_at: string;
  source: string;
};

export type PositionDetail = Position & {
  trade_history: TradeHistoryItem[];
  weight: number | null;
};

const API_BASE_URL = process.env.MARGIN_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { accept: "application/json" },
    next: { revalidate: 30 },
  });

  if (!response.ok) {
    throw new Error(`Margin API ${response.status}: ${path}`);
  }

  return response.json() as Promise<T>;
}

export function fetchPortfolioDashboard(
  portfolioId: string,
): Promise<PortfolioDashboard> {
  return request<PortfolioDashboard>(`/api/v1/portfolios/${portfolioId}`);
}

export function fetchPortfolioPositions(
  portfolioId: string,
): Promise<Position[]> {
  return request<Position[]>(`/api/v1/portfolios/${portfolioId}/positions`);
}

export function fetchPositionDetail(
  portfolioId: string,
  positionId: string,
): Promise<PositionDetail> {
  return request<PositionDetail>(
    `/api/v1/portfolios/${portfolioId}/positions/${positionId}`,
  );
}
