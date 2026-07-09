"use client";

/**
 * @fileoverview User-facing recommendation Q&A panel.
 */

import {
  ArrowUp,
  Check,
  CircleAlert,
  Clock3,
  LoaderCircle,
  PanelRight,
  Plus,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Textarea } from "@/components/ui/textarea";
import { notifyAgentChatSessionsChanged } from "@/lib/agent-chat-history";
import {
  askMainAgentQna,
  fetchAgentArtifact,
  fetchAgentChatSession,
  type AgentArtifactDetail,
  type AgentArtifactSummary,
  type AgentChatMessage,
  type AgentChatSession,
  type AgentChatSessionDetail,
  type MainAgentQnaResponse,
} from "@/lib/api";
import { useLanguage, type UiLanguage } from "@/lib/i18n";
import { cn } from "@/lib/utils";

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
  const [activityPanelOpen, setActivityPanelOpen] = useState(false);
  const conversationStartedRef = useRef(false);
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
  const latestActivityResponse = latestAssistantResponse(chatMessages);
  const activityState = busy
    ? "thinking"
    : latestActivityResponse
      ? "completed"
      : null;

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
        if (conversationStartedRef.current) {
          setLoadingSession(false);
          return;
        }
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
    conversationStartedRef.current = true;
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
                fetchArtifact={fetchArtifact}
                key={chatMessage.id}
                language={language}
                message={chatMessage}
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

            {activityState ? (
              <ChatActivityDock
                state={activityState}
                onOpen={() => setActivityPanelOpen(true)}
              />
            ) : null}
          </div>
        </div>
      )}

      {activityPanelOpen ? (
        <ChatActivityDrawer
          language={language}
          response={latestActivityResponse}
          state={activityState}
          onClose={() => setActivityPanelOpen(false)}
        />
      ) : null}

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
}: {
  fetchArtifact: (artifactId: string) => Promise<AgentArtifactDetail>;
  language: UiLanguage;
  message: ChatDisplayMessage;
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
          <SafeArtifactVisualization
            artifacts={message.response.artifacts}
            fetchArtifact={fetchArtifact}
          />
        </div>
      ) : null}
    </AssistantBlock>
  );
}

function SafeArtifactVisualization({
  artifacts,
  fetchArtifact,
}: {
  artifacts: AgentArtifactSummary[];
  fetchArtifact: (artifactId: string) => Promise<AgentArtifactDetail>;
}) {
  const safeArtifacts = useMemo(
    () =>
      artifacts.filter((artifact) =>
        ["chart_spec", "computed_metric", "visualization_image"].includes(
          artifact.artifact_type,
        ),
      ),
    [artifacts],
  );
  const safeArtifactIds = useMemo(
    () => safeArtifacts.map((artifact) => artifact.artifact_id).join("|"),
    [safeArtifacts],
  );
  const [details, setDetails] = useState<Record<string, AgentArtifactDetail>>({});

  useEffect(() => {
    if (safeArtifacts.length === 0) {
      return () => undefined;
    }
    let cancelled = false;
    for (const artifact of safeArtifacts) {
      void fetchArtifact(artifact.artifact_id).then((detail) => {
        if (cancelled) {
          return;
        }
        setDetails((current) => ({
          ...current,
          [artifact.artifact_id]: detail,
        }));
      });
    }
    return () => {
      cancelled = true;
    };
  }, [fetchArtifact, safeArtifactIds, safeArtifacts]);

  const chart = Object.values(details).find(
    (detail) => detail.artifact_type === "chart_spec",
  );
  const image = Object.values(details).find(
    (detail) => detail.artifact_type === "visualization_image",
  );
  const metric = Object.values(details).find(
    (detail) => detail.artifact_type === "computed_metric",
  );

  if (!chart && !image && !metric) {
    return null;
  }

  return (
    <div className="mt-5 grid max-w-2xl gap-3">
      {metric ? <MetricSummary detail={metric} /> : null}
      {image ? <SvgImageArtifact detail={image} /> : chart ? (
        <LineChartArtifact detail={chart} />
      ) : null}
    </div>
  );
}

function SvgImageArtifact({ detail }: { detail: AgentArtifactDetail }) {
  const payload = detail.payload_json;
  const svg = typeof payload.svg === "string" ? sanitizeSvgImage(payload.svg) : "";
  if (!svg) {
    return null;
  }
  return (
    <section
      aria-label={
        typeof payload.title === "string" ? payload.title : "数据可视化图"
      }
      className="overflow-hidden rounded-lg bg-muted/30 p-3"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

function MetricSummary({ detail }: { detail: AgentArtifactDetail }) {
  const payload = detail.payload_json;
  const label = typeof payload.label === "string" ? payload.label : "Metric";
  const value = typeof payload.latest_value === "number" ? payload.latest_value : null;
  const unit = typeof payload.unit === "string" ? payload.unit : "";
  if (value === null) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-baseline gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold text-foreground">
        {formatChartNumber(value)}
        {unit}
      </span>
    </div>
  );
}

function LineChartArtifact({ detail }: { detail: AgentArtifactDetail }) {
  const payload = detail.payload_json;
  const title = typeof payload.title === "string" ? payload.title : "指标趋势";
  const unit = typeof payload.unit === "string" ? payload.unit : "";
  const points = extractChartPoints(payload);
  if (points.length === 0) {
    return null;
  }
  const latest = points[points.length - 1];
  const coordinates = chartCoordinates(points);
  const path = coordinates.map((point) => `${point.x},${point.y}`).join(" ");
  return (
    <section className="grid gap-3 rounded-lg bg-muted/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {points[0].x} - {latest.x}
          </p>
        </div>
        <div className="text-right">
          <p className="text-lg font-semibold text-foreground">
            {formatChartNumber(latest.y)}
            {unit}
          </p>
          <p className="text-xs text-muted-foreground">最新值</p>
        </div>
      </div>
      <svg
        aria-label={title}
        className="h-28 w-full overflow-visible"
        role="img"
        viewBox="0 0 320 112"
      >
        <line className="stroke-border" x1="0" x2="320" y1="96" y2="96" />
        <polyline
          className="fill-none stroke-accent"
          points={path}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="3"
        />
        {points.map((point, index) => {
          const coordinate = coordinates[index];
          return (
            <circle
              className="fill-card stroke-accent"
              cx={coordinate.x}
              cy={coordinate.y}
              key={`${point.x}-${point.y}`}
              r="3"
              strokeWidth="2"
            />
          );
        })}
      </svg>
    </section>
  );
}

function ChatActivityDock({
  onOpen,
  state,
}: {
  onOpen: () => void;
  state: "completed" | "thinking" | null;
}) {
  if (!state) {
    return null;
  }
  const thinking = state === "thinking";
  return (
    <div className="max-w-[min(100%,56rem)]">
      <button
        aria-label="查看思考活动"
        className="inline-flex items-center gap-2 py-1 text-left text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        type="button"
        onClick={onOpen}
      >
        <span className="grid size-4 place-items-center">
          {thinking ? (
            <LoaderCircle className="size-4 animate-spin text-accent" />
          ) : (
            <PanelRight className="size-4" />
          )}
        </span>
        <span className="font-medium">查看思考活动</span>
        <span aria-hidden="true">·</span>
        <span className={cn("text-xs", thinking ? "text-accent" : "text-muted-foreground")}>
          {thinking ? "正在思考" : "思考完成"}
        </span>
      </button>
    </div>
  );
}

function ChatActivityDrawer({
  language,
  onClose,
  response,
  state,
}: {
  language: UiLanguage;
  onClose: () => void;
  response: MainAgentQnaResponse | null;
  state: "completed" | "thinking" | null;
}) {
  return (
    <aside
      aria-label="思考活动"
      className="fixed inset-y-0 right-0 z-50 grid w-[min(92vw,28rem)] grid-rows-[auto_minmax(0,1fr)] border-l border-border bg-card shadow-lg"
      role="dialog"
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Timeline
          </p>
          <h2 className="mt-1 text-sm font-semibold text-foreground">
            思考活动
          </h2>
        </div>
        <button
          aria-label="关闭思考活动"
          className="grid size-9 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          type="button"
          onClick={onClose}
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 overflow-y-auto p-4">
        {state === "thinking" ? (
          <ThinkingActivityLine language={language} />
        ) : response ? (
          <QnaActivityLine language={language} response={response} />
        ) : (
          <p className="rounded-lg border border-border bg-muted/20 p-3 text-sm text-muted-foreground">
            暂无可展示的思考活动。
          </p>
        )}
      </div>
    </aside>
  );
}

function ThinkingActivityLine({ language }: { language: UiLanguage }) {
  const rows = [
    {
      caption:
        language === "zh"
          ? "正在读取上下文并规划回答"
          : "Reading context and planning the answer",
      id: "thinking-main-agent",
      label: formatAgentName("MainAgent", language),
      skill: language === "zh" ? "上下文规划" : "context_planning",
      status: "running",
      state: "pending" as const,
    },
  ];
  return (
    <section
      aria-label={language === "zh" ? "本次活动" : "Activity"}
      className="rounded-lg border border-border bg-muted/20 p-3"
      data-testid="qna-activity-line"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">
          {language === "zh" ? "本次活动" : "Activity"}
        </p>
        <span className="rounded-full bg-accent/10 px-2 py-1 text-[11px] text-accent">
          正在思考
        </span>
      </div>
      <div className="grid">
        {rows.map((row, index) => (
          <QnaActivityRow
            isLast={index === rows.length - 1}
            key={row.id}
            language={language}
            row={row}
          />
        ))}
      </div>
    </section>
  );
}

function QnaActivityLine({
  language,
  response,
}: {
  language: UiLanguage;
  response: MainAgentQnaResponse;
}) {
  const rows = [
    {
      caption:
        language === "zh"
          ? "读取上下文并规划本次回答"
          : "Read context and planned this answer",
      id: "main-agent-plan",
      label: formatAgentName("MainAgent", language),
      skill: language === "zh" ? "上下文规划" : "context_planning",
      status: "planned",
      state: "completed" as const,
    },
    ...response.agent_trace.steps.map((step) => ({
      caption:
        language === "zh"
          ? "执行专家步骤并返回产物"
          : "Executed expert step and returned artifacts",
      id: step.step_id,
      label: formatAgentName(step.expert_agent_name, language),
      skill: step.skill_id,
      status: step.status,
      state: qnaStepState(step.status),
    })),
  ];

  return (
    <section
      aria-label={language === "zh" ? "本次活动" : "Activity"}
      className="rounded-lg border border-border bg-muted/20 p-3"
      data-testid="qna-activity-line"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">
          {language === "zh" ? "本次活动" : "Activity"}
        </p>
        <span className="rounded-full bg-muted px-2 py-1 text-[11px] text-muted-foreground">
          {language === "zh" ? `共 ${rows.length} 步` : `${rows.length} steps`}
        </span>
      </div>
      <div className="grid">
        {rows.map((row, index) => (
          <QnaActivityRow
            isLast={index === rows.length - 1}
            key={row.id}
            language={language}
            row={row}
          />
        ))}
      </div>
    </section>
  );
}

function QnaActivityRow({
  isLast,
  language,
  row,
}: {
  isLast: boolean;
  language: UiLanguage;
  row: {
    caption: string;
    id: string;
    label: string;
    skill: string;
    state: "completed" | "failed" | "pending";
    status: string;
  };
}) {
  const tone = qnaActivityTone(row.state);
  return (
    <article className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-3 pb-4 last:pb-0">
      <div className="relative flex justify-center">
        {!isLast ? (
          <span
            aria-hidden="true"
            className="absolute top-7 h-[calc(100%-0.25rem)] w-px bg-border"
          />
        ) : null}
        <span
          className={cn(
            "relative z-10 grid size-7 place-items-center rounded-full",
            tone.icon,
          )}
        >
          <QnaActivityIcon state={row.state} />
        </span>
      </div>
      <div className="min-w-0 rounded-md border border-border bg-card px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-medium text-foreground">{row.label}</h3>
          <span className={cn("rounded-full px-2 py-0.5 text-[11px]", tone.badge)}>
            {qnaActivityStatusText(row.state)}
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {row.caption}
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          <span className="rounded border border-border bg-muted px-2 py-1">
            {formatActivitySkill(row.skill, language)}
          </span>
          <span
            className={cn(
              "rounded border px-2 py-1",
              row.state === "failed"
                ? "border-negative/20 bg-negative-soft text-negative"
                : "border-border bg-muted",
            )}
          >
            {formatActivityStatusDetail(row.status, row.state, language)}
          </span>
        </div>
      </div>
    </article>
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

function latestAssistantResponse(
  messages: ChatDisplayMessage[],
): MainAgentQnaResponse | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const response = messages[index]?.response;
    if (response) {
      return response;
    }
  }
  return null;
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

function qnaStepState(status: string): "completed" | "failed" | "pending" {
  if (["completed", "succeeded", "succeeded_with_degradation"].includes(status)) {
    return "completed";
  }
  if (["cancelled", "failed", "failed_final", "upstream_failed"].includes(status)) {
    return "failed";
  }
  return "pending";
}

function QnaActivityIcon({
  state,
}: {
  state: "completed" | "failed" | "pending";
}) {
  if (state === "completed") {
    return <Check className="size-3.5" />;
  }
  if (state === "failed") {
    return <CircleAlert className="size-3.5" />;
  }
  return <Clock3 className="size-3.5" />;
}

function qnaActivityStatusText(
  state: "completed" | "failed" | "pending",
): string {
  if (state === "completed") {
    return "已完成";
  }
  if (state === "failed") {
    return "失败";
  }
  return "处理中";
}

function formatActivitySkill(skill: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    answer_research_question: { en: "Generate answer", zh: "生成回答" },
    context_planning: { en: "Context planning", zh: "上下文规划" },
    data_question: { en: "Analyze data", zh: "分析数据" },
    evidence_lookup: { en: "Check evidence", zh: "核验证据" },
    news_review: { en: "Review news", zh: "舆情复核" },
    quant_review: { en: "Review quant result", zh: "量化复核" },
  };
  return labels[skill]?.[language] ?? prettifyActivityIdentifier(skill);
}

function formatActivityStatusDetail(
  status: string,
  state: "completed" | "failed" | "pending",
  language: UiLanguage,
): string {
  if (state === "failed") {
    return language === "zh"
      ? `失败断点：${prettifyActivityIdentifier(status)}`
      : `Failed at: ${prettifyActivityIdentifier(status)}`;
  }
  if (status === "planned") {
    return language === "zh" ? "状态：已规划" : "Status: planned";
  }
  if (status === "running") {
    return language === "zh" ? "状态：进行中" : "Status: running";
  }
  if (status === "succeeded_with_degradation") {
    return language === "zh"
      ? "状态：已完成，有降级"
      : "Status: completed with degradation";
  }
  if (state === "completed") {
    return language === "zh" ? "状态：已完成" : "Status: completed";
  }
  return language === "zh" ? "状态：处理中" : "Status: running";
}

function prettifyActivityIdentifier(value: string): string {
  return value.replace(/[_-]+/g, " ").trim();
}

type ChartPoint = {
  x: string;
  y: number;
};

function extractChartPoints(payload: Record<string, unknown>): ChartPoint[] {
  const series = Array.isArray(payload.series) ? payload.series : [];
  const firstSeries = series.find(isRecord);
  const points = Array.isArray(firstSeries?.points) ? firstSeries.points : [];
  return points
    .filter(isRecord)
    .map((point) => ({
      x: typeof point.x === "string" ? point.x : String(point.x ?? ""),
      y: typeof point.y === "number" ? point.y : Number(point.y),
    }))
    .filter((point) => point.x && Number.isFinite(point.y));
}

function chartCoordinates(points: ChartPoint[]): Array<{ x: number; y: number }> {
  const values = points.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 300;
  const left = 10;
  const top = 12;
  const height = 84;
  return points.map((point, index) => ({
    x: left + (points.length === 1 ? width / 2 : (index / (points.length - 1)) * width),
    y: top + height - ((point.y - min) / range) * height,
  }));
}

function formatChartNumber(value: number): string {
  return value.toFixed(2);
}

function sanitizeSvgImage(svg: string): string {
  if (!svg.trim().startsWith("<svg")) {
    return "";
  }
  if (/<script[\s>]/i.test(svg) || /\son[a-z]+\s*=/i.test(svg)) {
    return "";
  }
  return svg;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function qnaActivityTone(state: "completed" | "failed" | "pending") {
  if (state === "completed") {
    return {
      badge: "bg-positive-soft text-positive",
      icon: "bg-positive text-white",
    };
  }
  if (state === "failed") {
    return {
      badge: "bg-negative-soft text-negative",
      icon: "bg-negative text-white",
    };
  }
  return {
    badge: "bg-muted text-muted-foreground",
    icon: "bg-muted-foreground text-white",
  };
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
