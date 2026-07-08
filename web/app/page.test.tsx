/**
 * @fileoverview Tests for the home page.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { askMainAgentQna } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

import HomePage from "./page";

vi.mock("@/lib/api", () => ({
  askMainAgentQna: vi.fn(),
  saveProviderSecret: vi.fn(),
  testProviderConfig: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((path: string) => {
    throw new Error(`unexpected redirect to ${path}`);
  }),
}));

describe("HomePage", () => {
  beforeEach(() => {
    vi.mocked(askMainAgentQna).mockResolvedValue({
      run_id: "ar_qna_1",
      answer: "今日推荐关注 000001。",
      guardrail: {
        allowed: true,
        decision: "allow",
        summary: "allowed",
        triggered_policies: [],
      },
      agent_trace: { steps: [] },
      artifacts: [],
      references: [{ api: "GET /api/v1/research", scope_version_id: "scope-current" }],
    });
  });

  it("renders a focused question-first home page", async () => {
    render(<LanguageProvider>{await HomePage()}</LanguageProvider>);

    expect(screen.getByRole("heading", { name: "今天想研究什么？" })).toBeInTheDocument();
    expect(screen.getByLabelText("投资研究问题")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    expect(screen.queryByText(/组合|持仓/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Provider|Scope|BFF|fail-closed/i)).not.toBeInTheDocument();
  });
});
