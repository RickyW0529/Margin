/**
 * @fileoverview Tests for the user-facing recommendation chat panel.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "@/lib/i18n";

import { RecommendationChatPanel } from "./recommendation-chat-panel";

afterEach(cleanup);

describe("RecommendationChatPanel", () => {
  it("asks the baseline recommendation question through the MainAgent runtime", async () => {
    const ask = vi.fn().mockResolvedValue({
      run_id: "ar_qna_1",
      answer: "今日推荐关注 000001、600000。",
      guardrail: {
        allowed: true,
        decision: "allow",
        summary: "allowed",
        triggered_policies: [],
      },
      agent_trace: {
        steps: [
          {
            step_id: "qna_1_dataanalyst",
            expert_agent_name: "DataAnalystAgent",
            skill_id: "answer_research_question",
            status: "succeeded",
          },
        ],
      },
      artifacts: [
        {
          artifact_type: "analysis_table",
          artifact_id: "ctx_1",
          producer_agent: "DataAnalystAgent",
          payload_hash: "sha256:test",
        },
      ],
      references: [{ api: "GET /api/v1/research", scope_version_id: "scope-current" }],
    });

    render(
      <LanguageProvider>
        <RecommendationChatPanel ask={ask} />
      </LanguageProvider>,
    );

    fireEvent.change(screen.getByLabelText("投资研究问题"), {
      target: { value: "今日推荐股票是什么？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(ask).toHaveBeenCalledWith({
        message: "今日推荐股票是什么？",
        scope_version_id: "scope-current",
        universe: "ALL_A",
        language: "zh",
      }),
    );
    expect(screen.getByText("今日推荐关注 000001、600000。")).toBeInTheDocument();
    expect(screen.getByText("研究智能体 → 数据分析师")).toBeInTheDocument();
    expect(screen.getByText("分析表")).toBeInTheDocument();
    expect(screen.getByText("推荐列表")).toBeInTheDocument();
    expect(screen.queryByText("GET /api/v1/research")).not.toBeInTheDocument();
  });
});
