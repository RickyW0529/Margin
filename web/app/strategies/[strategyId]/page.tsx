/**
 * @fileoverview Strategy detail page (server entry).
 * Loads the strategy profile and delegates rendering + lifecycle actions
 * to the client component.
 */

import { StrategyDetailClient } from "./strategy-detail-client";
import { fetchStrategyDetail } from "@/lib/api";

type StrategyDetailPageProps = {
  params: Promise<{ strategyId: string }>;
};

/** Renders one strategy profile with version lifecycle controls. */
export default async function StrategyDetailPage({ params }: StrategyDetailPageProps) {
  const { strategyId } = await params;
  let profile: Record<string, unknown> | null = null;
  let error: string | null = null;
  try {
    profile = await fetchStrategyDetail(strategyId);
  } catch {
    error = "策略加载失败";
  }
  return (
    <StrategyDetailClient
      strategyId={strategyId}
      initialProfile={profile}
      initialError={error}
    />
  );
}