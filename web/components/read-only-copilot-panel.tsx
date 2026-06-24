"use client";

/**
 * @fileoverview Read-only Copilot panel for dashboard Q&A.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  askReadOnlyCopilot,
  type ReadOnlyCopilotResponse,
} from "@/lib/api";

type ReadOnlyCopilotPanelProps = {
  scopeVersionId: string;
  universe?: string;
  ask?: (request: {
    scope_version_id: string;
    message: string;
    universe?: string;
  }) => Promise<ReadOnlyCopilotResponse>;
};

/** Renders a read-only Copilot that can only call read dashboard APIs. */
export function ReadOnlyCopilotPanel({
  scopeVersionId,
  universe = "ALL_A",
  ask = askReadOnlyCopilot,
}: ReadOnlyCopilotPanelProps) {
  const [message, setMessage] = useState("");
  const [response, setResponse] = useState<ReadOnlyCopilotResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit() {
    if (!message.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResponse(
        await ask({
          message: message.trim(),
          scope_version_id: scopeVersionId,
          universe,
        }),
      );
    } catch {
      setError("只读 Copilot 暂时不可用，或问题包含写入/刷新意图。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card aria-labelledby="readonly-copilot-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Read-only Copilot
          </p>
          <CardTitle id="readonly-copilot-title" className="mt-1">
            只读信息整合
          </CardTitle>
        </div>
        <span className="text-xs text-muted-foreground">{scopeVersionId}</span>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="grid gap-1.5">
          <Label>只读问题</Label>
          <Textarea
            aria-label="只读问题"
            onChange={(event) => setMessage(event.target.value)}
            placeholder="例如：今天哪些公司值得继续看？"
            rows={3}
            value={message}
          />
        </div>
        <Button
          onClick={handleSubmit}
          disabled={busy || !message.trim()}
          loading={busy}
        >
          询问只读 Copilot
        </Button>
        {error ? (
          <p className="text-xs text-negative" role="alert">
            {error}
          </p>
        ) : null}
        {response ? (
          <div className="grid gap-2 border-t border-border pt-3">
            <p className="text-sm leading-relaxed text-foreground">
              {response.answer}
            </p>
            <ul className="grid gap-1.5">
              {response.references.map((reference, index) => (
                <li
                  key={`${reference.api ?? "reference"}-${index}`}
                  className="flex items-center justify-between gap-2 rounded-md bg-muted/50 px-2.5 py-1.5"
                >
                  <span className="text-xs text-muted-foreground">
                    {reference.api ?? "reference"}
                  </span>
                  <strong className="text-xs text-foreground">
                    {reference.scope_version_id ?? scopeVersionId}
                  </strong>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
