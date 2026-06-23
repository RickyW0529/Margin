/**
 * @fileoverview Tests for v0.2 research run progress.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ResearchRunProgress } from "./research-run-progress";

afterEach(() => {
  cleanup();
});

describe("ResearchRunProgress", () => {
  it("shows partial counts and wait state", () => {
    render(
      <ResearchRunProgress
        run={{
          completed_count: 83,
          failed_count: 5,
          pending_count: 12,
          retry_after_seconds: 60,
          run_id: "run-1",
          status: "partial",
          supported_wait_states: ["waiting_rate_limit"],
          target_count: 100,
          trace_id: "trace-1",
          wait_state: "waiting_rate_limit",
          steps: [
            { step: "quant", status: "completed" },
            { step: "news_ai_review", status: "partial" },
          ],
        }}
      />,
    );

    expect(screen.getByText("83 / 100")).toBeInTheDocument();
    expect(screen.getByText("失败 5 · 待处理 12")).toBeInTheDocument();
    expect(screen.getByText("Provider 限流，约 60 秒后重试")).toBeInTheDocument();
    expect(screen.getByText("quant")).toBeInTheDocument();
    expect(screen.getByText("trace-1")).toBeInTheDocument();
  });
});
