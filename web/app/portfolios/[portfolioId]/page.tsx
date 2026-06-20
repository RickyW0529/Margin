/**
 * @fileoverview Portfolio detail page.
 * Loads a single portfolio's dashboard and positions for the portfolio workspace.
 */

import { PortfolioWorkspace } from "@/components/portfolio-workspace";
import {
  fetchPortfolioDashboard,
  fetchPortfolioPositions,
  type PortfolioDashboard,
  type Position,
} from "@/lib/api";

/**
 * Props for the portfolio detail page.
 */
type PortfolioPageProps = {
  params: Promise<{ portfolioId: string }>;
};

/**
 * Portfolio detail page that resolves route params and fetches portfolio data.
 * @param params - Route params containing the portfolio identifier.
 * @returns The portfolio workspace with dashboard and positions.
 */
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
