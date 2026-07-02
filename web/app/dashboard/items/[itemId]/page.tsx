/**
 * @fileoverview Recommendation detail route under the dashboard.
 */

import Link from "next/link";

import { RecommendationDetail } from "@/components/recommendation-detail";
import { fetchResearchItemDetailV2 } from "@/lib/api";

export const dynamic = "force-dynamic";

type RecommendationDetailPageProps = {
  params: Promise<{ itemId: string }>;
};

/** Renders one recommendation with detailed quant visuals and evidence. */
export default async function RecommendationDetailPage({
  params,
}: RecommendationDetailPageProps) {
  const { itemId } = await params;
  const detail = await fetchResearchItemDetailV2(itemId).catch(() => null);

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8 md:px-10">
      <Link
        className="text-sm font-medium text-muted-foreground no-underline hover:text-accent"
        href="/dashboard"
      >
        返回今日推荐
      </Link>
      {detail ? (
        <RecommendationDetail detail={detail} />
      ) : (
        <section
          className="rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          推荐详情暂时不可用。
        </section>
      )}
    </main>
  );
}
