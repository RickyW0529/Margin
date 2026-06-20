/**
 * @fileoverview Unit tests for the ReportPanel component.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportPanel } from "./report-panel";
import type { ReportExport, ResearchReport } from "@/lib/api";

/** Mock research report used in ReportPanel tests. */
const report: ResearchReport = {
  item_id: "di_1",
  run_id: "dr_1",
  symbol: "000001.SZ",
  title: "000001.SZ 研究报告",
  format: "markdown",
  content: "# 000001.SZ 研究报告\n\n本系统输出研究分析，不构成买卖指令。",
  sections: {
    summary: { symbol: "000001.SZ" },
  },
  generated_at: "2026-06-19T00:00:00Z",
};

/** Mock report export used in ReportPanel tests. */
const exported: ReportExport = {
  item_id: "di_1",
  format: "json",
  filename: "000001.SZ_di_1_research_report.json",
  mime_type: "application/json",
  content: "{}",
  generated_at: "2026-06-19T00:00:00Z",
};

/** Tests for ReportPanel rendering behavior. */
describe("ReportPanel", () => {
  it("renders report preview and export metadata", () => {
    render(<ReportPanel report={report} exported={exported} />);

    expect(screen.getByRole("heading", { name: "报告与导出" })).toBeInTheDocument();
    expect(screen.getByText("000001.SZ 研究报告")).toBeInTheDocument();
    expect(screen.getByText("application/json")).toBeInTheDocument();
    expect(screen.getByText(/不构成买卖指令/)).toBeInTheDocument();
  });
});
