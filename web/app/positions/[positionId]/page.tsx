/**
 * @fileoverview Position detail page.
 * Loads position details, alerts, and operation history for monitoring and review.
 */

import { PositionDetailView } from "@/components/position-detail";
import {
  fetchPositionAlerts,
  fetchPositionDetail,
  fetchPositionHistory,
  type AlertEvent,
  type OperationHistoryEntry,
  type PositionDetail,
} from "@/lib/api";

import { createPositionReviewAction, evaluatePositionAction } from "./actions";

/**
 * Props for the position detail page.
 */
type PositionPageProps = {
  params: Promise<{ positionId: string }>;
  searchParams: Promise<{ portfolioId?: string }>;
};

/**
 * Position detail page that fetches position data and binds server actions.
 * @param params - Route params containing the position identifier.
 * @param searchParams - Optional query params, including the portfolio identifier.
 * @returns The position detail view with monitoring actions.
 */
export default async function PositionPage({
  params,
  searchParams,
}: PositionPageProps) {
  const { positionId } = await params;
  const { portfolioId = "demo" } = await searchParams;
  let detail: PositionDetail | null = null;
  let alerts: AlertEvent[] = [];
  let history: OperationHistoryEntry[] = [];
  let error: string | null = null;

  try {
    [detail, alerts, history] = await Promise.all([
      fetchPositionDetail(portfolioId, positionId),
      fetchPositionAlerts(portfolioId, positionId),
      fetchPositionHistory(portfolioId, positionId),
    ]);
  } catch {
    error = "持仓数据暂时不可用";
  }

  return (
    <PositionDetailView
      portfolioId={portfolioId}
      evaluateAction={evaluatePositionAction.bind(null, positionId)}
      reviewAction={createPositionReviewAction.bind(null, positionId)}
      detail={detail}
      alerts={alerts}
      history={history}
      error={error}
    />
  );
}
