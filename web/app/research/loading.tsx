/**
 * @fileoverview Loading UI for the research dashboard route.
 */

import { PageLoading } from "@/components/page-loading";

/**
 * Fallback loading state shown while research dashboard data is being fetched.
 * @returns A centered loading indicator.
 */
export default function Loading() {
  return <PageLoading eyebrow="Research" title="研究候选面板" />;
}
