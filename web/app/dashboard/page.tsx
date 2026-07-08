/**
 * @fileoverview User-facing recommendation dashboard.
 */

import { RecommendationDashboardView } from "@/components/recommendation-dashboard-view";
import { fetchResearchCandidates } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Recommendation dashboard with cards, evidence summaries, and compact visuals. */
export default async function RecommendationDashboardPage() {
  const candidates = await fetchResearchCandidates({
    limit: 20,
    scope_version_id: "scope-current",
    universe: "ALL_A",
  }).catch(() => null);
  return <RecommendationDashboardView candidates={candidates} />;
}
