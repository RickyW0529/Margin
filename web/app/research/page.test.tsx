import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchProviderStatus,
  fetchResearchHome,
  fetchResearchRunCards,
  fetchResearchRuns,
} from "@/lib/api";

import ResearchDashboardPage from "./page";

vi.mock("@/lib/api", () => ({
  fetchProviderStatus: vi.fn(),
  fetchResearchHome: vi.fn(),
  fetchResearchRunCards: vi.fn(),
  fetchResearchRuns: vi.fn(),
}));

describe("ResearchDashboardPage", () => {
  beforeEach(() => {
    vi.mocked(fetchResearchHome).mockResolvedValue({
      decision_at: null,
      run_id: null,
      strategy_id: null,
      version_id: null,
      run_status: null,
      today_candidates: [],
      position_reviews: [],
      high_priority_risks: [],
      rejections: [],
      run_stats: {},
    });
    vi.mocked(fetchResearchRuns).mockResolvedValue([]);
    vi.mocked(fetchResearchRunCards).mockResolvedValue([]);
    vi.mocked(fetchProviderStatus).mockResolvedValue([
      {
        provider: "deepseek",
        status: "ready",
        message: "LLM 已配置",
      },
    ]);
  });

  it("renders a real research run form and provider status from the backend", async () => {
    render(await ResearchDashboardPage());

    expect(fetchProviderStatus).toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "启动研究运行" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("策略 ID")).toHaveValue("default");
    expect(screen.getByLabelText("标的代码")).toBeInTheDocument();
    expect(screen.getByText("deepseek")).toBeInTheDocument();
    expect(screen.getByText("LLM 已配置")).toBeInTheDocument();
  });
});
