"use client";

/**
 * @fileoverview User-facing recommendation Q&A panel.
 */

import { Send } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import {
  askReadOnlyCopilot,
  type ReadOnlyCopilotResponse,
} from "@/lib/api";

type RecommendationChatPanelProps = {
  ask?: (request: {
    scope_version_id: string;
    message: string;
    universe?: string;
  }) => Promise<ReadOnlyCopilotResponse>;
  scopeVersionId?: string;
  universe?: string;
};

const DEFAULT_QUESTION = "今日推荐股票是什么？";

function formatReferenceLabel(reference: Record<string, string>) {
  const api = reference.api ?? "";
  if (api.includes("/api/v1/research/items")) {
    return "公司详情";
  }
  if (api.includes("/api/v1/research")) {
    return "推荐列表";
  }
  return reference.title ?? "证据来源";
}

/** Renders the first-screen Q&A entry backed by read-only recommendation data. */
export function RecommendationChatPanel({
  ask = askReadOnlyCopilot,
  scopeVersionId = "scope-current",
  universe = "ALL_A",
}: RecommendationChatPanelProps) {
  const [message, setMessage] = useState("");
  const [response, setResponse] = useState<ReadOnlyCopilotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(nextMessage = message) {
    const trimmed = nextMessage.trim();
    if (!trimmed) {
      return;
    }
    setMessage(trimmed);
    setBusy(true);
    setError(null);
    try {
      setResponse(
        await ask({
          message: trimmed,
          scope_version_id: scopeVersionId,
          universe,
        }),
      );
    } catch {
      setError("暂时无法回答，请稍后再试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card aria-labelledby="recommendation-chat-title" className="overflow-hidden">
      <CardContent className="grid gap-5 p-5 md:p-6">
        <div className="grid gap-2">
          <h2
            id="recommendation-chat-title"
            className="text-2xl font-semibold tracking-tight text-foreground"
          >
            问答
          </h2>
          <button
            type="button"
            disabled={busy}
            onClick={() => submit(DEFAULT_QUESTION)}
            className="w-fit rounded-full border border-border bg-muted px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-card disabled:opacity-50"
          >
            {DEFAULT_QUESTION}
          </button>
        </div>

        <div className="grid gap-3">
          <Textarea
            aria-label="投资研究问题"
            className="min-h-[116px] resize-none text-base"
            disabled={busy}
            placeholder={DEFAULT_QUESTION}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button
              type="button"
              disabled={busy || !message.trim()}
              loading={busy}
              onClick={() => submit()}
            >
              <Send className="size-4" />
              发送
            </Button>
            <span className="text-xs text-muted-foreground">
              只读回答，不触发交易
            </span>
          </div>
        </div>

        {error ? (
          <p className="rounded-md border border-negative-soft bg-negative-soft px-3 py-2 text-sm text-negative" role="alert">
            {error}
          </p>
        ) : null}

        {response ? (
          <div className="grid gap-3 rounded-md border border-border bg-muted/40 p-4">
            <p className="text-sm leading-relaxed text-foreground">
              {response.answer}
            </p>
            {response.references.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {response.references.map((reference, index) => {
                  const label = formatReferenceLabel(reference);
                  return (
                    <span
                      key={`${label}-${index}`}
                      className="rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground"
                    >
                      {label}
                    </span>
                  );
                })}
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
