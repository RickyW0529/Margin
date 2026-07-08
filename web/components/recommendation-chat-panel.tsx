"use client";

/**
 * @fileoverview User-facing recommendation Q&A panel.
 */

import { ArrowUp, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Textarea } from "@/components/ui/textarea";
import {
  askMainAgentQna,
  type MainAgentQnaResponse,
} from "@/lib/api";
import { useLanguage, type UiLanguage } from "@/lib/i18n";
import {
  addRecentQuestion,
  updateRecentQuestion,
  useRecentQuestion,
} from "@/lib/recent-questions";

type RecommendationChatPanelProps = {
  ask?: (request: {
    scope_version_id: string;
    message: string;
    universe?: string;
    language?: UiLanguage;
  }) => Promise<MainAgentQnaResponse>;
  initialRecentQuestionId?: string | null;
  scopeVersionId?: string;
  universe?: string;
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
  initialRecentQuestionId = null,
  scopeVersionId = "scope-current",
  universe = "ALL_A",
}: RecommendationChatPanelProps) {
  const router = useRouter();
  const savedQuestion = useRecentQuestion(initialRecentQuestionId);
  const { language, t } = useLanguage();
  const [message, setMessage] = useState("");
  const [draftConversation, setDraftConversation] = useState<{
    error: string | null;
    response: MainAgentQnaResponse | null;
    submittedMessage: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const submittedMessage =
    draftConversation?.submittedMessage ?? savedQuestion?.text ?? null;
  const response =
    draftConversation !== null
      ? draftConversation.response
      : savedQuestion?.response ?? null;
  const error =
    draftConversation !== null
      ? draftConversation.error
      : savedQuestion?.error ?? null;
  const hasConversation = Boolean(submittedMessage || response || busy || error);

  async function submit(nextMessage = message) {
    const trimmed = nextMessage.trim();
    if (!trimmed) {
      return;
    }
    setDraftConversation({
      error: null,
      response: null,
      submittedMessage: trimmed,
    });
    setMessage("");
    const record = addRecentQuestion({
      language,
      scopeVersionId,
      text: trimmed,
      universe,
    });
    setBusy(true);
    try {
      const answer = await ask({
        message: trimmed,
        scope_version_id: scopeVersionId,
        universe,
        language,
      });
      setDraftConversation({
        error: null,
        response: answer,
        submittedMessage: trimmed,
      });
      if (record) {
        updateRecentQuestion(record.id, { error: null, response: answer });
        router.replace(`/?chat=${encodeURIComponent(record.id)}`, {
          scroll: false,
        });
      }
    } catch {
      const errorMessage = t("chatError");
      setDraftConversation({
        error: errorMessage,
        response: null,
        submittedMessage: trimmed,
      });
      if (record) {
        updateRecentQuestion(record.id, { error: errorMessage, response: null });
        router.replace(`/?chat=${encodeURIComponent(record.id)}`, {
          scroll: false,
        });
      }
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

            {submittedMessage ? (
              <div className="flex justify-end">
                <div className="max-w-[78%] rounded-[28px] bg-muted px-5 py-3 text-base leading-relaxed text-foreground shadow-sm md:max-w-[48rem]">
                  {submittedMessage}
                </div>
              </div>
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

            {error ? (
              <AssistantBlock>
                <p className="text-base leading-8 text-negative" role="alert">
                  {error}
                </p>
              </AssistantBlock>
            ) : null}

            {response ? (
              <AssistantBlock>
                <p className="text-base leading-8 text-foreground md:text-lg md:leading-9">
                  {response.answer}
                </p>
                <div className="mt-6 grid gap-3 text-sm text-muted-foreground">
                  <details>
                    <summary className="cursor-pointer text-muted-foreground transition-colors hover:text-foreground">
                      {t("chatTrace")}
                    </summary>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <span className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                        {formatAgentTrace(response.agent_trace.steps, language)}
                      </span>
                      {response.artifacts.map((artifact) => (
                        <span
                          key={artifact.artifact_id}
                          className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
                        >
                          {formatArtifactType(artifact.artifact_type, language)}
                        </span>
                      ))}
                    </div>
                  </details>
                  {response.references.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {response.references.map((reference, index) => {
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
                </div>
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
