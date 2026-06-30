/**
 * @fileoverview Tests for the finding card component.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FindingCard } from "@/components/finding-card";
import type { AnalysisFinding } from "@/lib/api";

afterEach(() => {
  cleanup();
});

const finding: AnalysisFinding = {
  finding_id: "af_001",
  finding_type: "value",
  severity: "info",
  title: "估值偏低",
  description: "PE 低于行业中位数。",
  confidence: 0.82,
  evidence_ids: ["ev_001", "ev_002"],
};

describe("FindingCard", () => {
  it("renders title, description, and severity badge", () => {
    render(<FindingCard finding={finding} />);
    expect(screen.getByText("估值偏低")).toBeInTheDocument();
    expect(screen.getByText("PE 低于行业中位数。")).toBeInTheDocument();
    expect(screen.getByText("信息")).toBeInTheDocument();
  });

  it("renders evidence id chips", () => {
    render(<FindingCard finding={finding} />);
    expect(screen.getByText("证据引用")).toBeInTheDocument();
  });

  it("hides evidence section when no evidence ids", () => {
    render(<FindingCard finding={{ ...finding, evidence_ids: [] }} />);
    expect(screen.queryByText("证据引用")).not.toBeInTheDocument();
  });

  it("renders critical severity badge for critical findings", () => {
    render(<FindingCard finding={{ ...finding, severity: "critical" }} />);
    expect(screen.getByText("严重")).toBeInTheDocument();
  });
});
