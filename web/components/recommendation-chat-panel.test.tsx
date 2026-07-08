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

import type {
  AgentArtifactDetail,
  AgentChatSessionDetail,
  MainAgentQnaResponse,
} from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

import { RecommendationChatPanel } from "./recommendation-chat-panel";

const navigationMocks = vi.hoisted(() => ({
  replace: vi.fn(),
  search: "",
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: navigationMocks.replace,
  }),
}));

afterEach(() => {
  cleanup();
  navigationMocks.replace.mockClear();
  navigationMocks.search = "";
});

describe("RecommendationChatPanel", () => {
  it("asks the baseline recommendation question through the MainAgent runtime", async () => {
    const ask = vi.fn().mockResolvedValue(
      makeQnaResponse({
        answer: "今日推荐关注 000001、600000。",
        sessionId: "acs_1",
      }),
    );
    const fetchArtifact = makeArtifactFetcher();

    render(
      <LanguageProvider>
        <RecommendationChatPanel ask={ask} fetchArtifact={fetchArtifact} />
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
        session_id: null,
        universe: "ALL_A",
        language: "zh",
      }),
    );
    expect(screen.getByText("今日推荐关注 000001、600000。")).toBeInTheDocument();
    expect(screen.getByText("研究智能体 → 数据分析师")).toBeInTheDocument();
    expect(screen.getAllByText("分析表").length).toBeGreaterThan(0);
    expect(screen.getByText("推荐列表")).toBeInTheDocument();
    expect(screen.queryByText("GET /api/v1/research")).not.toBeInTheDocument();

    const href = navigationMocks.replace.mock.calls[0]?.[0] as string;
    const chatId = new URL(`http://localhost${href}`).searchParams.get("chat");
    expect(chatId).toBe("acs_1");
  });

  it("restores a persisted conversation from the chat-session link", async () => {
    const savedResponse = makeQnaResponse({
      answer: "这是之前保存的回答。",
      runId: "ar_qna_saved",
      sessionId: "acs_saved",
    });
    const fetchSession = vi.fn().mockResolvedValue(
      makeSessionDetail({
        response: savedResponse,
        sessionId: "acs_saved",
        userMessage: "之前问过的问题",
      }),
    );
    const fetchArtifact = makeArtifactFetcher();

    render(
      <LanguageProvider>
        <RecommendationChatPanel
          ask={vi.fn()}
          fetchArtifact={fetchArtifact}
          fetchSession={fetchSession}
          initialChatSessionId="acs_saved"
        />
      </LanguageProvider>,
    );

    await waitFor(() =>
      expect(fetchSession).toHaveBeenCalledWith("acs_saved"),
    );
    expect(screen.getByText("之前问过的问题")).toBeInTheDocument();
    expect(screen.getByText("这是之前保存的回答。")).toBeInTheDocument();
    expect(screen.getByText("研究智能体 → 数据分析师")).toBeInTheDocument();
  });

  it("sends follow-up questions with the active persisted session id", async () => {
    const savedResponse = makeQnaResponse({
      answer: "这是之前保存的回答。",
      runId: "ar_qna_saved",
      sessionId: "acs_saved",
    });
    const fetchSession = vi.fn().mockResolvedValue(
      makeSessionDetail({
        response: savedResponse,
        sessionId: "acs_saved",
        userMessage: "之前问过的问题",
      }),
    );
    const fetchArtifact = makeArtifactFetcher();
    const ask = vi.fn().mockResolvedValue(
      makeQnaResponse({
        answer: "这是追问回答。",
        assistantMessageId: "acm_assistant_followup",
        runId: "ar_qna_followup",
        sessionId: "acs_saved",
        userMessageId: "acm_user_followup",
      }),
    );

    render(
      <LanguageProvider>
        <RecommendationChatPanel
          ask={ask}
          fetchArtifact={fetchArtifact}
          fetchSession={fetchSession}
          initialChatSessionId="acs_saved"
        />
      </LanguageProvider>,
    );

    await screen.findByText("这是之前保存的回答。");
    fireEvent.change(screen.getByLabelText("投资研究问题"), {
      target: { value: "继续解释一下" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(ask).toHaveBeenCalledWith({
        message: "继续解释一下",
        scope_version_id: "scope-current",
        session_id: "acs_saved",
        universe: "ALL_A",
        language: "zh",
      }),
    );
    expect(screen.getByText("继续解释一下")).toBeInTheDocument();
    expect(screen.getByText("这是追问回答。")).toBeInTheDocument();
  });

  it("expands analysis-table artifacts below assistant messages", async () => {
    const ask = vi.fn().mockResolvedValue(
      makeQnaResponse({
        answer: "我整理了一张候选表。",
        sessionId: "acs_table",
      }),
    );
    const fetchArtifact = vi.fn().mockResolvedValue(
      makeArtifactDetail({
        artifactId: "ctx_1",
        artifactType: "analysis_table",
        payload: {
          rows: [
            { symbol: "000001.SZ", name: "平安银行", final_score: 86 },
            { symbol: "600000.SH", name: "浦发银行", final_score: 82 },
          ],
        },
      }),
    );

    render(
      <LanguageProvider>
        <RecommendationChatPanel ask={ask} fetchArtifact={fetchArtifact} />
      </LanguageProvider>,
    );

    fireEvent.change(screen.getByLabelText("投资研究问题"), {
      target: { value: "给我一张候选表" },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "发送" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await screen.findByText("我整理了一张候选表。");
    await waitFor(() => expect(fetchArtifact).toHaveBeenCalledWith("ctx_1"));
    expect(screen.getByText("000001.SZ")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByText("86")).toBeInTheDocument();
    expect(screen.getByText("sha256:test")).toBeInTheDocument();
  });
});

function makeQnaResponse({
  answer,
  assistantMessageId = "acm_assistant_1",
  runId = "ar_qna_1",
  sessionId,
  userMessageId = "acm_user_1",
}: {
  answer: string;
  assistantMessageId?: string;
  runId?: string;
  sessionId: string;
  userMessageId?: string;
}): MainAgentQnaResponse {
  return {
    answer,
    assistant_message_id: assistantMessageId,
    run_id: runId,
    session_id: sessionId,
    user_message_id: userMessageId,
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
    references: [
      { api: "GET /api/v1/research", scope_version_id: "scope-current" },
    ],
  };
}

function makeArtifactFetcher() {
  return vi.fn().mockResolvedValue(
    makeArtifactDetail({
      artifactId: "ctx_1",
      artifactType: "analysis_table",
      payload: {
        rows: [{ symbol: "000001.SZ", name: "平安银行", final_score: 86 }],
      },
    }),
  );
}

function makeArtifactDetail({
  artifactId,
  artifactType,
  payload,
}: {
  artifactId: string;
  artifactType: string;
  payload: Record<string, unknown>;
}): AgentArtifactDetail {
  return {
    artifact_id: artifactId,
    artifact_type: artifactType,
    created_at: "2026-07-08T10:01:00Z",
    evidence_refs: [],
    payload_hash: "sha256:test",
    payload_json: payload,
    producer_agent: "DataAnalystAgent",
    run_id: "ar_qna_1",
    source_refs: ["GET /api/v1/research"],
  };
}

function makeSessionDetail({
  response,
  sessionId,
  userMessage,
}: {
  response: MainAgentQnaResponse;
  sessionId: string;
  userMessage: string;
}): AgentChatSessionDetail {
  return {
    session: {
      created_at: "2026-07-08T10:00:00Z",
      language: "zh",
      scope_version_id: "scope-current",
      session_id: sessionId,
      title: userMessage,
      universe: "ALL_A",
      updated_at: "2026-07-08T10:01:00Z",
    },
    messages: [
      {
        content: userMessage,
        created_at: "2026-07-08T10:00:00Z",
        message_id: response.user_message_id,
        payload: {},
        role: "user",
        run_id: null,
        session_id: sessionId,
      },
      {
        content: response.answer,
        created_at: "2026-07-08T10:01:00Z",
        message_id: response.assistant_message_id,
        payload: response,
        role: "assistant",
        run_id: response.run_id,
        session_id: sessionId,
      },
    ],
  };
}
