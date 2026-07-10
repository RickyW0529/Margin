import type { UiLanguage } from "@/lib/i18n";

const REASON_LABELS: Record<string, Record<UiLanguage, string>> = {
  catalyst_only_conservative_weight: {
    en: "Earnings-only idea uses a conservative position cap",
    zh: "仅由财报催化入选，采用保守仓位上限",
  },
  new_filing_reviewed_from_rag: {
    en: "New filing reviewed from the evidence library",
    zh: "已复核证据库中的最新财报",
  },
  quant_passed: { en: "Passed the quant screen", zh: "通过量化筛选" },
  rag_delta_review_completed: {
    en: "Completed filing delta review",
    zh: "已完成财报增量复核",
  },
  deep_drawdown: { en: "Deep historical drawdown", zh: "历史回撤较深" },
  high_volatility: { en: "High volatility", zh: "波动率偏高" },
  short_term_overheat: { en: "Short-term price overheat", zh: "短期涨幅过热" },
  websearch_counter_evidence_requires_thesis_recheck: {
    en: "Counter-evidence found; thesis requires review",
    zh: "发现反面证据，需要重新审视原结论",
  },
  websearch_did_not_find_obvious_counter_evidence: {
    en: "No obvious counter-evidence found in web verification",
    zh: "公开信息复核未发现明显反证",
  },
  weighted_signal_passed: {
    en: "Passed the weighted-signal model",
    zh: "通过加权信号模型",
  },
};

/** Convert durable machine reason codes into concise user-facing labels. */
export function recommendationReasonLabel(
  reason: string,
  language: UiLanguage,
): string {
  const normalized = reason.trim();
  const known = REASON_LABELS[normalized.toLowerCase().replaceAll(" ", "_")];
  if (known) {
    return known[language];
  }
  if (/^[a-z0-9_-]+$/i.test(normalized)) {
    const readable = normalized.replace(/[_-]+/g, " ");
    return readable.charAt(0).toUpperCase() + readable.slice(1);
  }
  return normalized;
}

/** Convert durable recommendation source IDs into accurate user-facing labels. */
export function recommendationSourceLabel(
  source: string,
  language: UiLanguage,
): string {
  const normalized = source.toLowerCase();
  if (normalized.includes("catalyst") || normalized.includes("earnings")) {
    return language === "zh" ? "财报催化" : "Earnings catalyst";
  }
  if (normalized.includes("websearch") || normalized.includes("counter")) {
    return language === "zh" ? "公开信息反证" : "Web counter-evidence";
  }
  if (normalized.includes("rag") || normalized.includes("filing")) {
    return language === "zh" ? "RAG 文档证据" : "RAG document evidence";
  }
  if (normalized.includes("fusion")) {
    return language === "zh" ? "推荐融合" : "Recommendation fusion";
  }
  if (normalized.includes("quant") || normalized.includes("ml")) {
    return language === "zh" ? "ML 量化" : "ML quant";
  }
  return source;
}
