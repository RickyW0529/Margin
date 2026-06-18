import { PositionDetailView } from "@/components/position-detail";
import { fetchPositionDetail, type PositionDetail } from "@/lib/api";

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
  let error: string | null = null;

  try {
    detail = await fetchPositionDetail(portfolioId, positionId);
  } catch {
    error = "持仓数据暂时不可用";
  }

  return (
    <PositionDetailView
      portfolioId={portfolioId}
      detail={detail}
      error={error}
    />
  );
}
