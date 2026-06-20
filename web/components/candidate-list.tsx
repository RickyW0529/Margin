/**
 * @fileoverview Grid component that renders a collection of research candidate
 * cards, or an empty state when no candidates are available.
 */

import type { ResearchCandidateCard } from "@/lib/api";
import { CandidateCard } from "./candidate-card";

/** Props for the CandidateList component. */
type CandidateListProps = {
  /** Array of research candidate cards to render. */
  cards: ResearchCandidateCard[];
};

/**
 * Renders a grid of candidate cards.
 *
 * @param cards Research candidates to display.
 * @returns The candidate grid or an empty state.
 */
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
