/**
 * @fileoverview Unit tests for the EvidencePanel component.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidencePanel } from "./evidence-panel";
import type { EvidenceView } from "@/lib/api";

/** Mock evidence view used in EvidencePanel tests. */
const evidence: EvidenceView = {
  item_id: "di_1",
  claims: [
    {
      claim_id: "cl_1",
      statement: "经营现金流改善",
      fact_or_inference: "fact",
      confidence: 0.82,
      has_conflict: false,
      evidence_ids: ["ev_1"],
    },
  ],
  evidence_by_level: {
    unknown: [
      {
        evidence_id: "ev_1",
        source_level: "unknown",
        source_url: "https://example.com",
        content: "现金流数据",
        page: 3,
        section: "财务摘要",
      },
    ],
  },
  source_distribution: { unknown: 1 },
  overall_confidence: 0.82,
  locators_available: true,
};

/** Tests for EvidencePanel rendering behavior. */
describe("EvidencePanel", () => {
  it("renders claims and source locators", () => {
    render(<EvidencePanel evidence={evidence} />);

    expect(screen.getByText("经营现金流改善")).toBeInTheDocument();
    expect(screen.getByText("ev_1")).toBeInTheDocument();
    expect(screen.getByText(/第 3 页/)).toBeInTheDocument();
  });
});
