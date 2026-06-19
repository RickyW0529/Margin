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

export type AlertEvent = {
  alert_id: string;
  portfolio_id: string;
  position_id: string;
  symbol: string;
  alert_type: string;
  severity: "P0" | "P1" | "P2" | "P3";
  message: string;
  rule_name: string;
  triggered_at: string;
  evidence_refs: string[];
  changed_thesis: boolean;
  acknowledged_at: string | null;
};

export type OperationHistoryEntry = {
  event_id: string;
  position_id: string;
  event_type: string;
  occurred_at: string;
  summary: string;
  metadata: Record<string, unknown>;
};

export type ResearchRun = {
  run_id: string;
  decision_at: string;
  strategy_id: string;
  version_id: string;
  portfolio_id: string | null;
  universe: string[];
  status: string;
  summary: string;
  item_count: number;
  published_count: number;
  abstained_count: number;
  aborted_count: number;
  created_at: string;
};

export type ResearchItem = {
  item_id: string;
  run_id: string;
  symbol: string;
  signal_type: string;
  confidence: number;
  statement: string;
  workflow_run_id: string;
  snapshot_id: string | null;
  status: string;
  abstain_reason: string | null;
  rejection_reasons: string[];
  evidence_ids: string[];
  claim_ids: string[];
  risk_score: number | null;
  counter_arguments: string[];
  portfolio_constraint_violations: string[];
  created_at: string;
};

export type ResearchCandidateCard = {
  item_id: string;
  run_id: string;
  symbol: string;
  signal_type: string;
  confidence: number;
  statement: string;
  current_price: number | null;
  quantitative_rank: number | null;
  research_status: string;
  position_review_status: string | null;
  valuation_range: [number, number] | null;
  margin_of_safety: number | null;
  value_trap_score: number | null;
  event_window: string | null;
  catalysts: string[];
  counter_arguments: string[];
  evidence_summary: { count?: number; levels?: Record<string, number> };
  watch_conditions: string[];
  invalidation_conditions: string[];
  strategy_version: string;
  disclaimer: string;
};

export type ClaimView = {
  claim_id: string;
  statement: string;
  fact_or_inference: string;
  confidence: number;
  has_conflict: boolean;
  evidence_ids: string[];
};

export type EvidenceLocator = {
  evidence_id: string;
  source_level: string;
  source_url: string | null;
  content: string;
  page: number | null;
  section: string | null;
};

export type EvidenceView = {
  item_id: string;
  claims: ClaimView[];
  evidence_by_level: Record<string, EvidenceLocator[]>;
  source_distribution: Record<string, number>;
  overall_confidence: number;
  locators_available: boolean;
};

export type ValuationView = {
  item_id: string;
  base_valuation_range: [number, number] | null;
  pessimistic_range: [number, number] | null;
  margin_of_safety: number | null;
  value_trap_score: number | null;
  method: string | null;
  notes: string;
};

export type AuditView = {
  item_id: string;
  workflow_run_id: string;
  snapshot_id: string | null;
  workflow_state: string | null;
  input_hash: string | null;
  output_hash: string | null;
  trace_count: number;
  tool_call_ids: string[];
  error: string | null;
};

export type ResearchHomeSummary = {
  decision_at: string | null;
  run_id: string | null;
  strategy_id: string | null;
  version_id: string | null;
  run_status: string | null;
  today_candidates: ResearchCandidateCard[];
  position_reviews: ResearchCandidateCard[];
  high_priority_risks: ResearchCandidateCard[];
  rejections: ResearchCandidateCard[];
  run_stats: Record<string, number>;
};

export type FeedbackRecord = {
  feedback_id: string;
  item_id: string;
  feedback_type: string;
  comment: string;
  created_at: string;
};

export type ProviderStatus = {
  provider: string;
  status: string;
  message: string;
};

export type ResearchReport = {
  item_id: string;
  run_id: string;
  symbol: string;
  title: string;
  format: "markdown" | "json";
  content: string;
  sections: Record<string, unknown>;
  generated_at: string;
};

export type ReportExport = {
  item_id: string;
  format: "markdown" | "json";
  filename: string;
  mime_type: string;
  content: string;
  generated_at: string;
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

export function fetchPositionAlerts(
  portfolioId: string,
  positionId: string,
): Promise<AlertEvent[]> {
  const query = new URLSearchParams({ portfolio_id: portfolioId });
  return request<AlertEvent[]>(
    `/api/v1/positions/${positionId}/alerts?${query.toString()}`,
  );
}

export function fetchPositionHistory(
  portfolioId: string,
  positionId: string,
): Promise<OperationHistoryEntry[]> {
  const query = new URLSearchParams({ portfolio_id: portfolioId });
  return request<OperationHistoryEntry[]>(
    `/api/v1/positions/${positionId}/history?${query.toString()}`,
  );
}

export function fetchResearchRuns(): Promise<ResearchRun[]> {
  return request<ResearchRun[]>("/api/v1/research-runs");
}

export function fetchResearchRun(runId: string): Promise<ResearchRun> {
  return request<ResearchRun>(`/api/v1/research-runs/${runId}`);
}

export function fetchResearchRunItems(runId: string): Promise<ResearchItem[]> {
  return request<ResearchItem[]>(`/api/v1/research-runs/${runId}/items`);
}

export function fetchResearchRunCards(
  runId: string,
): Promise<ResearchCandidateCard[]> {
  return request<ResearchCandidateCard[]>(
    `/api/v1/research-runs/${runId}/cards`,
  );
}

export function fetchResearchHome(): Promise<ResearchHomeSummary> {
  return request<ResearchHomeSummary>("/api/v1/research-home");
}

export function fetchResearchItem(itemId: string): Promise<ResearchItem> {
  return request<ResearchItem>(`/api/v1/research-items/${itemId}`);
}

export function fetchResearchItemEvidence(
  itemId: string,
): Promise<EvidenceView> {
  return request<EvidenceView>(`/api/v1/research-items/${itemId}/evidence`);
}

export function fetchResearchItemValuation(
  itemId: string,
): Promise<ValuationView> {
  return request<ValuationView>(`/api/v1/research-items/${itemId}/valuation`);
}

export function fetchResearchItemAudit(itemId: string): Promise<AuditView> {
  return request<AuditView>(`/api/v1/research-items/${itemId}/audit`);
}

export function fetchResearchItemReport(itemId: string): Promise<ResearchReport> {
  return request<ResearchReport>(`/api/v1/research-items/${itemId}/report`);
}

export function fetchResearchItemExport(
  itemId: string,
  format: "markdown" | "json" = "markdown",
): Promise<ReportExport> {
  return request<ReportExport>(
    `/api/v1/research-items/${itemId}/export?format=${format}`,
  );
}

export function fetchProviderStatus(): Promise<ProviderStatus[]> {
  return request<ProviderStatus[]>("/api/v1/provider-status");
}
