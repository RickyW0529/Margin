import type { ResearchCandidateCard } from "@/lib/api";
import { CandidateCard } from "./candidate-card";

type CandidateListProps = {
  cards: ResearchCandidateCard[];
};

export function CandidateList({ cards }: CandidateListProps) {
  if (cards.length === 0) {
    return <div className="empty-state">暂无研究候选</div>;
  }

  return (
    <div className="candidate-grid">
      {cards.map((card) => (
        <CandidateCard key={card.item_id} card={card} />
      ))}
    </div>
  );
}
