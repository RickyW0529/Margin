/**
 * @fileoverview Question-first home page for the Margin workspace.
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { RecommendationChatPanel } from "@/components/recommendation-chat-panel";
import { Button } from "@/components/ui/button";
import {
  fetchResearchCandidates,
  type ResearchCandidateListItemV2,
} from "@/lib/api";
import { formatScore } from "@/lib/utils";

export const dynamic = "force-dynamic";

/** Home page focused on natural-language research questions. */
export default async function HomePage() {
  const candidates = await fetchResearchCandidates({
    limit: 3,
    scope_version_id: "scope-current",
    universe: "ALL_A",
  }).catch(() => null);
  const items = candidates?.items ?? [];

  return (
    <main className="mx-auto grid min-h-[calc(100vh-3.5rem)] max-w-5xl content-center gap-7 px-6 py-8 md:px-10">
      <section className="grid gap-3">
        <p className="text-sm text-muted-foreground">Margin</p>
        <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
          今天想研究什么？
        </h1>
      </section>

      <RecommendationChatPanel />

      <section className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-foreground">今日推荐预览</h2>
          <Button asChild size="sm" variant="secondary">
            <Link href="/dashboard">
              打开今日推荐 <ArrowRight className="size-4" />
            </Link>
          </Button>
        </div>
        {items.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-3">
            {items.map((item) => (
              <RecommendationPreview key={item.item_id} item={item} />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border bg-card px-4 py-6 text-sm text-muted-foreground">
            今日暂无推荐。
          </div>
        )}
      </section>
    </main>
  );
}

function RecommendationPreview({ item }: { item: ResearchCandidateListItemV2 }) {
  return (
    <Link
      href={`/dashboard?item_id=${encodeURIComponent(item.item_id)}#recommendation-detail`}
      className="grid gap-3 rounded-lg border border-border bg-card p-4 no-underline transition-colors hover:bg-muted/50"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="grid gap-0.5">
          <strong className="text-sm text-foreground">{item.name}</strong>
          <span className="text-xs text-muted-foreground">{item.symbol}</span>
        </span>
        <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
          {item.screening_status}
        </span>
      </div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-muted-foreground">评分</span>
        <strong className="text-foreground">{formatScore(item.final_score)}</strong>
      </div>
    </Link>
  );
}
