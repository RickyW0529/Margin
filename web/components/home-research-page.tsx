"use client";

/**
 * @fileoverview Minimal GPT-style research question landing page.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { RecommendationChatPanel } from "@/components/recommendation-chat-panel";
import { useLanguage } from "@/lib/i18n";

/** Renders the simplified question-first home page. */
export function HomeResearchPage() {
  const { t } = useLanguage();
  const searchParams = useSearchParams();
  const selectedChatId = searchParams.get("chat");
  return (
    <main className="min-h-[calc(100vh-3.5rem)] bg-background text-foreground">
      <Link className="sr-only" href="/dashboard">
        {t("homeBrandLink")}
      </Link>
      <RecommendationChatPanel
        initialRecentQuestionId={selectedChatId}
        key={selectedChatId ?? "new-chat"}
      />
    </main>
  );
}
