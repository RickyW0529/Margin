import { PortfolioWorkspace } from "@/components/portfolio-workspace";
import {
  fetchPortfolioDashboard,
  fetchPortfolioPositions,
  type PortfolioDashboard,
  type Position,
} from "@/lib/api";

type PortfolioPageProps = {
  params: Promise<{ portfolioId: string }>;
};

export default async function PortfolioPage({ params }: PortfolioPageProps) {
  const { portfolioId } = await params;
  let dashboard: PortfolioDashboard | null = null;
  let positions: Position[] = [];
  let error: string | null = null;

  try {
    [dashboard, positions] = await Promise.all([
      fetchPortfolioDashboard(portfolioId),
      fetchPortfolioPositions(portfolioId),
    ]);
  } catch {
    error = "组合数据暂时不可用";
  }

  return (
    <PortfolioWorkspace
      dashboard={dashboard}
      positions={positions}
      error={error}
    />
  );
}
