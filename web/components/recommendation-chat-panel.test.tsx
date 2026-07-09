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
    expect(screen.getByRole("button", { name: "查看思考活动" }))
      .toBeInTheDocument();
    expect(screen.getByText("思考完成")).toBeInTheDocument();
    expect(screen.queryByText("answer_research_question")).toBeNull();
    expect(screen.queryByText("sha256:test")).toBeNull();
    expect(screen.getByText("推荐列表")).toBeInTheDocument();
    expect(screen.queryByText("GET /api/v1/research")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看思考活动" }));
    expect(screen.getByRole("dialog", { name: "思考活动" })).toBeInTheDocument();
    expect(screen.getByText("研究智能体")).toBeInTheDocument();
    expect(screen.getByText("数据分析师")).toBeInTheDocument();
    expect(screen.getByText("生成回答")).toBeInTheDocument();
    expect(screen.queryByText("answer_research_question")).toBeNull();
    expect(screen.getAllByText("状态：已完成").length).toBeGreaterThan(0);

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
    expect(screen.queryByTestId("qna-activity-line")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "查看思考活动" }));
    expect(screen.getByText("数据分析师")).toBeInTheDocument();
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

  it("does not render raw artifacts below assistant messages", async () => {
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
    await waitFor(() => expect(ask).toHaveBeenCalled());
    expect(fetchArtifact).not.toHaveBeenCalled();
    expect(screen.queryByText("000001.SZ")).toBeNull();
    expect(screen.queryByText("平安银行")).toBeNull();
    expect(screen.queryByText("sha256:test")).toBeNull();
  });

  it("renders safe chart artifacts without exposing raw artifact JSON", async () => {
    const ask = vi.fn().mockResolvedValue(
      makeQnaResponse({
        answer: "中国平安最近一期 ROE TTM 为 12.30%。",
        artifacts: [
          {
            artifact_id: "ctx_table",
            artifact_type: "analysis_table",
            payload_hash: "sha256:table",
            producer_agent: "DataQuestionWorker",
          },
          {
            artifact_id: "ctx_metric",
            artifact_type: "computed_metric",
            payload_hash: "sha256:metric",
            producer_agent: "DataQuestionWorker",
          },
          {
            artifact_id: "ctx_chart",
            artifact_type: "chart_spec",
            payload_hash: "sha256:chart",
            producer_agent: "DataQuestionWorker",
          },
          {
            artifact_id: "ctx_image",
            artifact_type: "visualization_image",
            payload_hash: "sha256:image",
            producer_agent: "DataQuestionWorker",
          },
        ],
        sessionId: "acs_roe",
      }),
    );
    const fetchArtifact = vi.fn(async (artifactId: string) => {
      if (artifactId === "ctx_metric") {
        return makeArtifactDetail({
          artifactId,
          artifactType: "computed_metric",
          payload: {
            label: "ROE TTM",
            latest_value: 12.3,
            unit: "%",
          },
        });
      }
      if (artifactId === "ctx_image") {
        return makeArtifactDetail({
          artifactId,
          artifactType: "visualization_image",
          payload: {
            chart_type: "bar",
            image_format: "svg",
            title: "中国平安 ROE TTM 趋势",
            svg: '<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="中国平安 ROE TTM 趋势"><rect x="0" y="0" width="10" height="10"/></svg>',
          },
        });
      }
      return makeArtifactDetail({
        artifactId,
        artifactType: "chart_spec",
        payload: {
          chart_type: "line",
          title: "中国平安 ROE TTM 趋势",
          unit: "%",
          series: [
            {
              label: "ROE TTM",
              metric: "roe_ttm",
              points: [
                { x: "2023-12-31", y: 10.1 },
                { x: "2024-12-31", y: 12.3 },
              ],
            },
          ],
        },
      });
    });

    render(
      <LanguageProvider>
        <RecommendationChatPanel ask={ask} fetchArtifact={fetchArtifact} />
      </LanguageProvider>,
    );

    fireEvent.change(screen.getByLabelText("投资研究问题"), {
      target: { value: "中国平安最近 ROE 怎么样？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(
      await screen.findByRole("img", { name: "中国平安 ROE TTM 趋势" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("12.30%").length).toBeGreaterThan(0);
    expect(fetchArtifact).toHaveBeenCalledWith("ctx_metric");
    expect(fetchArtifact).toHaveBeenCalledWith("ctx_chart");
    expect(fetchArtifact).toHaveBeenCalledWith("ctx_image");
    expect(fetchArtifact).not.toHaveBeenCalledWith("ctx_table");
    expect(screen.queryByText("中国平安 ROE TTM 趋势")).toBeNull();
    expect(screen.queryByText("sha256:chart")).toBeNull();
    expect(screen.queryByText("sha256:image")).toBeNull();
    expect(screen.queryByText("Chart spec")).toBeNull();
  });

  it("shows a clickable thinking activity entry while the request is running", async () => {
    let resolveAnswer: (response: MainAgentQnaResponse) => void = () => undefined;
    const ask = vi.fn(
      () =>
        new Promise<MainAgentQnaResponse>((resolve) => {
          resolveAnswer = resolve;
        }),
    );

    render(
      <LanguageProvider>
        <RecommendationChatPanel ask={ask} fetchArtifact={makeArtifactFetcher()} />
      </LanguageProvider>,
    );

    fireEvent.change(screen.getByLabelText("投资研究问题"), {
      target: { value: "帮我分析今天候选" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("正在思考")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看思考活动" }));
    expect(screen.getByRole("dialog", { name: "思考活动" })).toBeInTheDocument();
    expect(screen.getByText("正在读取上下文并规划回答")).toBeInTheDocument();

    resolveAnswer(
      makeQnaResponse({
        answer: "完成。",
        sessionId: "acs_running",
      }),
    );
  });
});

function makeQnaResponse({
  answer,
  artifacts,
  assistantMessageId = "acm_assistant_1",
  runId = "ar_qna_1",
  sessionId,
  userMessageId = "acm_user_1",
}: {
  answer: string;
  artifacts?: MainAgentQnaResponse["artifacts"];
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
    artifacts: artifacts ?? [
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
