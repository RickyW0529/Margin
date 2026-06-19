import { CandidateList } from "@/components/candidate-list";
import {
  fetchResearchRun,
  fetchResearchRunCards,
  type ResearchCandidateCard,
  type ResearchRun,
} from "@/lib/api";

type ResearchRunPageProps = {
  params: Promise<{ runId: string }>;
};

export default async function ResearchRunPage({ params }: ResearchRunPageProps) {
  const { runId } = await params;
  let run: ResearchRun | null = null;
  let cards: ResearchCandidateCard[] = [];
  let error: string | null = null;

  try {
    [run, cards] = await Promise.all([
      fetchResearchRun(runId),
      fetchResearchRunCards(runId),
    ]);
  } catch {
    error = "研究运行数据暂时不可用";
  }

  return (
    <main className="workspace-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">Research Run</p>
          <h1>{run?.run_id ?? runId}</h1>
        </div>
        <div className="status-strip">
          <span>{run?.status ?? "--"}</span>
          <span>{run?.item_count ?? 0} 个研究项</span>
        </div>
      </section>
      {error ? (
        <div className="notice-panel" role="alert">{error}</div>
      ) : (
        <CandidateList cards={cards} />
      )}
    </main>
  );
}
