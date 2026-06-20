/**
 * @fileoverview Loading UI for the home route.
 */

import { PageLoading } from "@/components/page-loading";

/**
 * Fallback loading state shown while the home page data is being fetched.
 * @returns A centered loading indicator.
 */
export default function Loading() {
  return <PageLoading eyebrow="Margin" title="Margin 工作台" />;
}
