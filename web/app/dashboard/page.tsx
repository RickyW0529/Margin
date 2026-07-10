/**
 * @fileoverview User-facing recommendation dashboard.
 */

import { RecommendationDashboardView } from "@/components/recommendation-dashboard-view";
import {
  fetchResearchCandidates,
  type ResearchCandidateListResponse,
} from "@/lib/api";

export const dynamic = "force-dynamic";

const RECOMMENDATION_PAGE_SIZE = 200;

async function loadResearchCandidates(): Promise<ResearchCandidateListResponse> {
  const firstPage = await fetchResearchCandidates({
    limit: RECOMMENDATION_PAGE_SIZE,
    scope_version_id: "scope-current",
    universe: "ALL_A",
  });
  const items = [...firstPage.items];
  const seenCursors = new Set<string>();
  let page = firstPage;

  while (page.page_info.has_next_page && page.page_info.next_cursor) {
    const cursor = page.page_info.next_cursor;
    if (seenCursors.has(cursor)) {
      throw new Error("Research pagination returned a repeated cursor");
    }
    seenCursors.add(cursor);
    page = await fetchResearchCandidates({
      cursor,
      limit: RECOMMENDATION_PAGE_SIZE,
      scope_version_id: "scope-current",
      universe: "ALL_A",
    });
    items.push(...page.items);
  }

  return {
    ...firstPage,
    items,
    page_info: {
      ...page.page_info,
      has_next_page: false,
      next_cursor: null,
      page_size: items.length,
    },
  };
}

/** Recommendation dashboard with cards, evidence summaries, and compact visuals. */
export default async function RecommendationDashboardPage() {
  const candidates = await loadResearchCandidates().catch(() => null);
  return <RecommendationDashboardView candidates={candidates} />;
}
