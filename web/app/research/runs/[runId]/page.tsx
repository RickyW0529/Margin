/**
 * @fileoverview Research run detail page.
 * Polls valuation-discovery run status until terminal and renders progress.
 */

import { runDetailPageLoader } from "./run-detail-client";

type ResearchRunPageProps = {
  params: Promise<{ runId: string }>;
};

/** Server entry that hands the run id to the polling client component. */
export default async function ResearchRunPage({ params }: ResearchRunPageProps) {
  const { runId } = await params;
  return runDetailPageLoader(runId);
}