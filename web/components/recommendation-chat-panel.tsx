"use client";

/**
 * @fileoverview User-facing recommendation Q&A panel.
 */

import { ArrowUp, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AgentArtifactPanel } from "@/components/agent-artifact-panel";
import { Textarea } from "@/components/ui/textarea";
import { notifyAgentChatSessionsChanged } from "@/lib/agent-chat-history";
import {
  askMainAgentQna,
  fetchAgentArtifact,
  fetchAgentChatSession,
  type AgentArtifactDetail,
  type AgentChatMessage,
  type AgentChatSession,
  type AgentChatSessionDetail,
  type MainAgentQnaResponse,
} from "@/lib/api";
import { useLanguage, type UiLanguage } from "@/lib/i18n";

type RecommendationChatPanelProps = {
  ask?: (request: {
    scope_version_id: string;
    message: string;
    session_id?: string | null;
    universe?: string;
    language?: UiLanguage;
  }) => Promise<MainAgentQnaResponse>;
  fetchArtifact?: (artifactId: string) => Promise<AgentArtifactDetail>;
  fetchSession?: (sessionId: string) => Promise<AgentChatSessionDetail>;
  initialChatSessionId?: string | null;
  scopeVersionId?: string;
  universe?: string;
};

type ChatDisplayMessage = {
  content: string;
  id: string;
  response?: MainAgentQnaResponse | null;
  role: "assistant" | "user";
};

function formatReferenceLabel(
  reference: Record<string, string>,
  language: UiLanguage,
) {
  const api = reference.api ?? "";
  if (api.includes("/api/v1/research/items")) {
    return language === "zh" ? "公司详情" : "Company detail";
  }
  if (api.includes("/api/v1/research")) {
    return language === "zh" ? "推荐列表" : "Recommendation list";
  }
  return reference.title ?? (language === "zh" ? "证据来源" : "Evidence source");
}

/** Renders the first-screen Q&A entry backed by read-only recommendation data. */
export function RecommendationChatPanel({
  ask = askMainAgentQna,
  fetchArtifact = fetchAgentArtifact,
  fetchSession = fetchAgentChatSession,
  initialChatSessionId = null,
  scopeVersionId = "scope-current",
  universe = "ALL_A",
}: RecommendationChatPanelProps) {
  const router = useRouter();
  const { language, t } = useLanguage();
  const [message, setMessage] = useState("");
  const [activeSession, setActiveSession] = useState<AgentChatSession | null>(
    null,
  );
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    initialChatSessionId,
  );
  const [chatMessages, setChatMessages] = useState<ChatDisplayMessage[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(
    null,
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const requestScopeVersionId = activeSession?.scope_version_id ?? scopeVersionId;
  const requestUniverse = activeSession?.universe ?? universe;
  const requestLanguage =
    activeSession?.language === "en" || activeSession?.language === "zh"
      ? activeSession.language
      : language;
  const hasConversation = Boolean(
    loadingSession ||
      loadError ||
      chatMessages.length > 0 ||
      pendingUserMessage ||
      busy ||
      submitError,
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return () => undefined;
    }
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      setActiveSessionId(initialChatSessionId);
      setPendingUserMessage(null);
      setSubmitError(null);
      setLoadError(false);
      if (!initialChatSessionId) {
        setActiveSession(null);
        setChatMessages([]);
        setLoadingSession(false);
        return;
      }
      setLoadingSession(true);
      fetchSession(initialChatSessionId)
        .then((detail) => {
          if (cancelled) {
            return;
          }
          setActiveSession(detail.session);
          setActiveSessionId(detail.session.session_id);
          setChatMessages(detail.messages.map(mapPersistedChatMessage));
        })
        .catch(() => {
          if (cancelled) {
            return;
          }
          setActiveSession(null);
          setChatMessages([]);
          setLoadError(true);
        })
        .finally(() => {
          if (!cancelled) {
            setLoadingSession(false);
          }
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [fetchSession, initialChatSessionId]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return () => undefined;
    }
    if (initialChatSessionId) {
      return;
    }
    const timeoutId = window.setTimeout(() => {
      if (!busy) {
        setLoadingSession(false);
      }
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [busy, initialChatSessionId]);

  async function submit(nextMessage = message) {
    const trimmed = nextMessage.trim();
    if (!trimmed) {
      return;
    }
    setPendingUserMessage(trimmed);
    setSubmitError(null);
    setMessage("");
    setBusy(true);
    try {
      const answer = await ask({
        message: trimmed,
        scope_version_id: requestScopeVersionId,
        session_id: activeSessionId,
        universe: requestUniverse,
        language: requestLanguage,
      });
      setActiveSessionId(answer.session_id);
      setActiveSession((current) =>
        current ??
        newSessionFromAnswer({
          answer,
          language: requestLanguage,
          scopeVersionId: requestScopeVersionId,
          title: trimmed,
          universe: requestUniverse,
        }),
      );
      setChatMessages((current) => [
        ...current,
        {
          content: trimmed,
          id: answer.user_message_id,
          role: "user",
        },
        {
          content: answer.answer,
          id: answer.assistant_message_id,
          response: answer,
          role: "assistant",
        },
      ]);
      setPendingUserMessage(null);
      notifyAgentChatSessionsChanged();
      if (answer.session_id !== initialChatSessionId) {
        router.replace(`/?chat=${encodeURIComponent(answer.session_id)}`, {
          scroll: false,
        });
      }
    } catch {
      const errorMessage = t("chatError");
      setSubmitError(errorMessage);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label={t("navAsk")}
      className="relative grid h-[calc(100vh-3.5rem)] grid-rows-[minmax(0,1fr)_auto]"
    >
      {!hasConversation ? (
        <div className="grid min-h-0 place-items-center px-5 pb-10 pt-20 md:px-10">
          <div className="mx-auto grid w-full max-w-5xl gap-8 text-center">
            <div className="grid justify-items-center gap-3">
              <h1 className="max-w-3xl text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
                {t("homeTitle")}
              </h1>
            </div>
            <ChatComposer
              busy={busy}
              message={message}
              placeholder={t("chatPlaceholder")}
              setMessage={setMessage}
              submit={submit}
              t={t}
            />
          </div>
        </div>
      ) : (
        <div className="min-h-0 overflow-y-auto px-5 pb-40 pt-20 md:px-10 md:pb-44 md:pt-24">
          <div className="mx-auto grid min-h-full w-full max-w-6xl content-start gap-8">
            {loadingSession ? (
              <AssistantBlock>
                <p className="text-base leading-8 text-foreground">
                  {t("chatReadingData")}
                </p>
              </AssistantBlock>
            ) : null}

            {loadError ? (
              <AssistantBlock>
                <p className="text-base leading-8 text-negative" role="alert">
                  {t("chatError")}
                </p>
              </AssistantBlock>
            ) : null}

            {chatMessages.map((chatMessage) => (
              <ChatMessageBubble
                key={chatMessage.id}
                fetchArtifact={fetchArtifact}
                language={language}
                message={chatMessage}
                t={t}
              />
            ))}

            {pendingUserMessage ? (
              <UserMessageBubble message={pendingUserMessage} />
            ) : null}

            {busy ? (
              <AssistantBlock>
                <p className="text-base leading-8 text-foreground">
                  {t("chatThinking")}
                </p>
                <p className="mt-7 text-base text-muted-foreground">
                  {t("chatReadingData")}
                </p>
              </AssistantBlock>
            ) : null}

            {submitError ? (
              <AssistantBlock>
                <p className="text-base leading-8 text-negative" role="alert">
                  {submitError}
                </p>
              </AssistantBlock>
            ) : null}
          </div>
        </div>
      )}

      {hasConversation ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-background via-background to-transparent px-5 pb-5 pt-16 md:px-10">
          <ChatComposer
            busy={busy}
            message={message}
            placeholder={t("chatFollowupPlaceholder")}
            setMessage={setMessage}
            submit={submit}
            t={t}
          />
        </div>
      ) : null}
    </section>
  );
}

function UserMessageBubble({ message }: { message: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[78%] rounded-[28px] bg-muted px-5 py-3 text-base leading-relaxed text-foreground shadow-sm md:max-w-[48rem]">
        {message}
      </div>
    </div>
  );
}

function ChatMessageBubble({
  fetchArtifact,
  language,
  message,
  t,
}: {
  fetchArtifact: (artifactId: string) => Promise<AgentArtifactDetail>;
  language: UiLanguage;
  message: ChatDisplayMessage;
  t: ReturnType<typeof useLanguage>["t"];
}) {
  if (message.role === "user") {
    return <UserMessageBubble message={message.content} />;
  }
  return (
    <AssistantBlock>
      <p className="text-base leading-8 text-foreground md:text-lg md:leading-9">
        {message.content}
      </p>
      {message.response ? (
        <div className="mt-6 grid gap-3 text-sm text-muted-foreground">
          <details>
            <summary className="cursor-pointer text-muted-foreground transition-colors hover:text-foreground">
              {t("chatTrace")}
            </summary>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                {formatAgentTrace(message.response.agent_trace.steps, language)}
              </span>
              {message.response.artifacts.map((artifact) => (
                <span
                  key={artifact.artifact_id}
                  className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
                >
                  {formatArtifactType(artifact.artifact_type, language)}
                </span>
              ))}
            </div>
          </details>
          {message.response.references.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {message.response.references.map((reference, index) => {
                const label = formatReferenceLabel(reference, language);
                return (
                  <span
                    key={`${label}-${index}`}
                    className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
                  >
                    {label}
                  </span>
                );
              })}
            </div>
          ) : null}
          <AgentArtifactPanel
            artifacts={message.response.artifacts}
            fetchArtifact={fetchArtifact}
            language={language}
          />
        </div>
      ) : null}
    </AssistantBlock>
  );
}

function ChatComposer({
  busy,
  message,
  placeholder,
  setMessage,
  submit,
  t,
}: {
  busy: boolean;
  message: string;
  placeholder: string;
  setMessage: (message: string) => void;
  submit: () => Promise<void>;
  t: ReturnType<typeof useLanguage>["t"];
}) {
  return (
    <form
      className="pointer-events-auto mx-auto grid w-full max-w-5xl gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="flex min-h-16 items-end gap-3 rounded-[32px] border border-border bg-card px-4 py-3 shadow-lg">
        <button
          aria-label={t("chatAttach")}
          className="mb-1 grid size-9 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
          disabled={busy}
          type="button"
        >
          <Plus className="size-5" />
        </button>
        <Textarea
          aria-label={t("chatLabel")}
          className="max-h-40 min-h-10 flex-1 resize-none border-0 bg-transparent px-0 py-2 text-base leading-6 text-foreground shadow-none outline-none placeholder:text-muted-foreground focus-visible:ring-0"
          disabled={busy}
          placeholder={placeholder}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button
          aria-label={t("chatSend")}
          className="mb-0.5 grid size-10 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-transform hover:scale-105 disabled:scale-100 disabled:bg-muted disabled:text-muted-foreground"
          disabled={busy || !message.trim()}
          type="submit"
        >
          {busy ? (
            <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
          ) : (
            <ArrowUp className="size-5" />
          )}
        </button>
      </div>
      <p className="text-center text-xs text-muted-foreground">
        {t("chatDisclaimer")}
      </p>
    </form>
  );
}

function AssistantBlock({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-[min(100%,56rem)] text-left">
      {children}
    </div>
  );
}

function formatAgentTrace(
  steps: MainAgentQnaResponse["agent_trace"]["steps"],
  language: UiLanguage,
): string {
  const agents = steps.map((step) =>
    formatAgentName(step.expert_agent_name, language),
  );
  return [formatAgentName("MainAgent", language), ...agents].join(" → ");
}

function formatAgentName(agentName: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    CodeSandboxAgent: { en: "Code sandbox", zh: "代码沙箱" },
    DataAnalystAgent: { en: "Data analyst", zh: "数据分析师" },
    DataInspectionAgent: { en: "Data check", zh: "数据检查" },
    MainAgent: { en: "Research agent", zh: "研究智能体" },
    NewsAcquisitionAgent: { en: "News research", zh: "新闻获取" },
    QuantAgent: { en: "Quant analysis", zh: "量化分析" },
    StockAnalystAgent: { en: "Stock analyst", zh: "股票分析师" },
  };
  return labels[agentName]?.[language] ?? agentName;
}

function formatArtifactType(artifactType: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    analysis_table: { en: "Analysis table", zh: "分析表" },
    chart_spec: { en: "Chart spec", zh: "图表说明" },
    computed_metric: { en: "Computed metric", zh: "计算指标" },
    explanation: { en: "Explanation", zh: "解释文本" },
    generated_file_ref: { en: "Generated file", zh: "生成文件" },
  };
  return labels[artifactType]?.[language] ?? artifactType;
}

function mapPersistedChatMessage(message: AgentChatMessage): ChatDisplayMessage {
  const response =
    message.role === "assistant" && isMainAgentQnaResponse(message.payload)
      ? message.payload
      : null;
  return {
    content: message.content,
    id: message.message_id,
    response,
    role: message.role,
  };
}

function isMainAgentQnaResponse(
  value: Record<string, unknown>,
): value is MainAgentQnaResponse {
  return (
    typeof value.answer === "string" &&
    typeof value.run_id === "string" &&
    typeof value.session_id === "string" &&
    typeof value.user_message_id === "string" &&
    typeof value.assistant_message_id === "string" &&
    Array.isArray(value.artifacts) &&
    Array.isArray(value.references) &&
    typeof value.agent_trace === "object" &&
    value.agent_trace !== null
  );
}

function newSessionFromAnswer({
  answer,
  language,
  scopeVersionId,
  title,
  universe,
}: {
  answer: MainAgentQnaResponse;
  language: UiLanguage;
  scopeVersionId: string;
  title: string;
  universe: string;
}): AgentChatSession {
  const now = new Date().toISOString();
  return {
    session_id: answer.session_id,
    title: title.trim().slice(0, 80) || "Untitled research chat",
    scope_version_id: scopeVersionId,
    universe,
    language,
    created_at: now,
    updated_at: now,
  };
}
