/**
 * @fileoverview Loading UI for the position detail route.
 */

import { PageLoading } from "@/components/page-loading";

/**
 * Fallback loading state shown while position data is being fetched.
 * @returns A centered loading indicator.
 */
export default function Loading() {
  return <PageLoading eyebrow="Position" title="持仓详情" />;
}
