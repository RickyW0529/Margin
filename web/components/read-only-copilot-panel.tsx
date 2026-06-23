"use client";

/**
 * @fileoverview Read-only Copilot panel for dashboard Q&A.
 */

import { useState } from "react";

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
  const [response, setResponse] = useState<ReadOnlyCopilotResponse | null>(null);
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
    <section className="panel" aria-labelledby="readonly-copilot-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Read-only Copilot</p>
          <h2 id="readonly-copilot-title">只读信息整合</h2>
        </div>
        <span>{scopeVersionId}</span>
      </div>
      <div className="action-form">
        <label className="form-field">
          <span>只读问题</span>
          <textarea
            aria-label="只读问题"
            onChange={(event) => setMessage(event.target.value)}
            placeholder="例如：今天哪些公司值得继续看？"
            rows={3}
            value={message}
          />
        </label>
        <button
          className="primary-button"
          disabled={busy || !message.trim()}
          onClick={handleSubmit}
          type="button"
        >
          {busy ? "查询中…" : "询问只读 Copilot"}
        </button>
      </div>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {response ? (
        <div className="copilot-answer">
          <p>{response.answer}</p>
          <ul className="event-list">
            {response.references.map((reference, index) => (
              <li key={`${reference.api ?? "reference"}-${index}`}>
                <span>{reference.api ?? "reference"}</span>
                <strong>{reference.scope_version_id ?? scopeVersionId}</strong>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
