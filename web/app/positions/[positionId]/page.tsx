import { PositionDetailView } from "@/components/position-detail";
import {
  fetchPositionAlerts,
  fetchPositionDetail,
  fetchPositionHistory,
  type AlertEvent,
  type OperationHistoryEntry,
  type PositionDetail,
} from "@/lib/api";

type PositionPageProps = {
  params: Promise<{ positionId: string }>;
  searchParams: Promise<{ portfolioId?: string }>;
};

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
      detail={detail}
      alerts={alerts}
      history={history}
      error={error}
    />
  );
}
