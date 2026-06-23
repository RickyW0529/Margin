/**
 * @fileoverview Tests for the v0.2 valuation-discovery run detail page.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchResearchRunDetailV2 } from "@/lib/api";

import ResearchRunPage from "./page";

vi.mock("@/lib/api", () => ({
  fetchResearchRunDetailV2: vi.fn(),
}));

describe("ResearchRunPage", () => {
  beforeEach(() => {
    vi.mocked(fetchResearchRunDetailV2).mockResolvedValue({
      completed_count: 1,
      failed_count: 0,
      pending_count: 1,
      retry_after_seconds: null,
      run_id: "vdr-1",
      status: "succeeded",
      steps: [
        { status: "succeeded", step: "QUANT_RUN" },
        { status: "waiting_budget", step: "NEWS_REFRESH", error_code: "provider_budget_exceeded" },
      ],
      supported_wait_states: ["waiting_provider", "waiting_rate_limit", "waiting_retry"],
      target_count: 2,
      trace_id: "vdr-1",
      wait_state: null,
    });
  });

  it("renders v0.2 run status and polls once for a terminal run", async () => {
    await act(async () => {
      render(await ResearchRunPage({ params: Promise.resolve({ runId: "vdr-1" }) }));
    });

    await waitFor(() => expect(fetchResearchRunDetailV2).toHaveBeenCalledWith("vdr-1"));
    expect(screen.getByRole("heading", { name: "vdr-1" })).toBeInTheDocument();
    expect(screen.getByText("运行进度")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });
});