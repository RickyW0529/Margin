/**
 * @fileoverview Loading UI for the research item detail route.
 */

import { PageLoading } from "@/components/page-loading";

/**
 * Fallback loading state shown while research item data is being fetched.
 * @returns A centered loading indicator.
 */
export default function Loading() {
  return <PageLoading eyebrow="Research Item" title="研究详情" />;
}
