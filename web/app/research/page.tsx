import { CandidateList } from "@/components/candidate-list";
import { HomeSummary } from "@/components/home-summary";
import { ProviderStatusPanel } from "@/components/provider-status-panel";
import { ResearchRunForm } from "@/components/research-run-form";
import {
  fetchProviderStatus,
  fetchResearchHome,
  fetchResearchRunCards,
  fetchResearchRuns,
  type ProviderStatus,
  type ResearchCandidateCard,
  type ResearchHomeSummary,
  type ResearchRun,
} from "@/lib/api";

import { createResearchRunAction } from "./actions";

export const dynamic = "force-dynamic";

export default async function ResearchDashboardPage() {
  let summary: ResearchHomeSummary | null = null;
  let runs: ResearchRun[] = [];
  let cards: ResearchCandidateCard[] = [];
  let providers: ProviderStatus[] = [];
  let error: string | null = null;

  try {
    [summary, runs, providers] = await Promise.all([
      fetchResearchHome(),
      fetchResearchRuns(),
      fetchProviderStatus(),
    ]);
    if (runs[0]) {
      cards = await fetchResearchRunCards(runs[0].run_id);
    }
  } catch {
    error = "研究候选数据暂时不可用";
  }

  return (
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="research-title">
        <div>
          <p className="eyebrow">Research</p>
          <h1 id="research-title">研究候选面板</h1>
        </div>
        <div className="status-strip">
          <span>不是买卖指令</span>
          <span>{runs.length} 个运行批次</span>
        </div>
      </section>

      {error ? (
        <div className="notice-panel" role="alert">
          <span>{error}</span>
        </div>
      ) : (
        <>
          <section className="workspace-grid">
            <ResearchRunForm action={createResearchRunAction} />
            <ProviderStatusPanel providers={providers} title="研究 Provider 状态" />
          </section>
          <HomeSummary summary={summary} />
          <section className="panel">
            <div className="panel-heading">
              <h2>今日候选</h2>
              <span>{cards.length} cards</span>
            </div>
            <CandidateList cards={cards} />
          </section>
        </>
      )}
    </main>
  );
}
