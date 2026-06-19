import { ShieldAlert } from "lucide-react";
import Link from "next/link";

import type { ResearchCandidateCard } from "@/lib/api";
import { PositionReviewBadge } from "./position-review-badge";
import { ResearchStatusBadge } from "./research-status-badge";

type CandidateCardProps = {
  card: ResearchCandidateCard;
};

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 0,
});

function moneyRange(range: [number, number] | null): string {
  if (!range) {
    return "估值暂不可用";
  }
  return `${currency.format(range[0])} – ${currency.format(range[1])}`;
}

function score(value: number | null): string {
  return value == null ? "--" : percent.format(value);
}

export function CandidateCard({ card }: CandidateCardProps) {
  const evidenceCount = card.evidence_summary.count ?? 0;

  return (
    <article className="candidate-card">
      <div className="candidate-card-header">
        <div>
          <p className="eyebrow">Research Candidate</p>
          <h2>
            <Link className="card-title-link" href={`/research/items/${card.item_id}`}>
              {card.symbol}
            </Link>
          </h2>
        </div>
        <div className="status-strip">
          <ResearchStatusBadge status={card.research_status} />
          <PositionReviewBadge status={card.position_review_status} />
        </div>
      </div>

      <p className="candidate-statement">{card.statement || "暂无研究结论"}</p>

      <dl className="candidate-facts">
        <div>
          <dt>置信度</dt>
          <dd>{score(card.confidence)}</dd>
        </div>
        <div>
          <dt>估值区间</dt>
          <dd>{moneyRange(card.valuation_range)}</dd>
        </div>
        <div>
          <dt>价值陷阱风险</dt>
          <dd>{score(card.value_trap_score)}</dd>
        </div>
        <div>
          <dt>证据</dt>
          <dd>证据 {evidenceCount}</dd>
        </div>
      </dl>

      {card.counter_arguments.length > 0 ? (
        <div className="counter-box">
          <ShieldAlert aria-hidden="true" size={16} />
          <div>
            <strong>最强反方理由</strong>
            <ul>
              {card.counter_arguments.map((argument) => (
                <li key={argument}>{argument}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      <div className="candidate-footer">
        <span>策略版本 {card.strategy_version || "--"}</span>
        <span>{card.disclaimer}</span>
      </div>
    </article>
  );
}
