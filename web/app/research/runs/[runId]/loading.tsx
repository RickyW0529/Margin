/**
 * @fileoverview Loading UI for the research run detail route.
 */

import { PageLoading } from "@/components/page-loading";

/**
 * Fallback loading state shown while research run data is being fetched.
 * @returns A centered loading indicator.
 */
export default function Loading() {
  return <PageLoading eyebrow="Research Run" title="研究运行" />;
}
