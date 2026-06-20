/**
 * @fileoverview Loading UI for the portfolio detail route.
 */

import { PageLoading } from "@/components/page-loading";

/**
 * Fallback loading state shown while portfolio data is being fetched.
 * @returns A centered loading indicator.
 */
export default function Loading() {
  return <PageLoading eyebrow="Portfolio" title="组合看板" />;
}
