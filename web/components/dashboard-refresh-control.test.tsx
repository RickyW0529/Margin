/**
 * @fileoverview Tests for the dashboard refresh control and live node graph.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ResearchRunDetailV2 } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

import { DashboardRefreshControl } from "./dashboard-refresh-control";

const routerMocks = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerMocks.refresh,
  }),
}));

const baseRun = {
  completed_count: 1,
  failed_count: 0,
  pending_count: 11,
  retry_after_seconds: null,
  status: "running",
  supported_wait_states: ["waiting_provider", "waiting_rate_limit", "waiting_retry"],
  target_count: 12,
  trace_id: "run-1",
  wait_state: null,
} satisfies Omit<ResearchRunDetailV2, "run_id" | "steps">;

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  routerMocks.refresh.mockClear();
  vi.restoreAllMocks();
});

describe("DashboardRefreshControl", () => {
  it("opens the latest run graph and marks completed, queued, and pending nodes", async () => {
    const startRefresh = vi.fn().mockResolvedValue({
      http_status: 202,
      run_id: "run-1",
      status: "accepted",
    });
    const fetchRunDetail = vi.fn().mockResolvedValue({
      ...baseRun,
      run_id: "run-1",
      steps: [
        { status: "succeeded", step: "DATA_FRESHNESS_CHECK" },
        {
          finished_at: null,
          started_at: "2026-07-01T04:00:01Z",
          status: "pending",
          step: "DATA_SYNC",
        },
      ],
    });

    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue(null)}
        fetchRunDetail={fetchRunDetail}
        now={() => new Date("2026-07-01T04:00:00.000Z")}
        startRefresh={startRefresh}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "启动今日研究" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Agent 协作进度",
    });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveClass("fixed");
    expect(screen.getByText("run-1")).toBeInTheDocument();
    expect(screen.getByTestId("agent-collaboration-feed")).toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-main_agent_dispatch"))
      .toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-data_inspection")).toHaveAttribute(
      "data-agent-state",
      "queued",
    );
    expect(screen.getByTestId("agent-activity-quant_analysis")).toHaveAttribute(
      "data-agent-state",
      "pending",
    );
    expect(
      screen.getByRole("progressbar", { name: "量化分析 progress" }),
    ).toHaveAttribute("aria-valuenow", "6");
    expect(screen.queryByRole("link", { name: "查看详情" })).toBeNull();
    expect(startRefresh).toHaveBeenCalledWith({
      decision_at: "2026-07-01T04:00:00.000Z",
      scope_version_id: "scope-current",
    });
  });

  it("keeps only the newest refresh graph when users start another run", async () => {
    const startRefresh = vi
      .fn()
      .mockResolvedValueOnce({
        http_status: 202,
        run_id: "run-old",
        status: "accepted",
      })
      .mockResolvedValueOnce({
        http_status: 202,
        run_id: "run-new",
        status: "accepted",
      });
    const fetchRunDetail = vi.fn((runId: string) =>
      Promise.resolve({
        ...baseRun,
        completed_count: runId === "run-old" ? 12 : baseRun.completed_count,
        pending_count: runId === "run-old" ? 0 : baseRun.pending_count,
        run_id: runId,
        status: runId === "run-old" ? "succeeded" : baseRun.status,
        steps: [{ status: "succeeded", step: "DATA_FRESHNESS_CHECK" }],
      }),
    );

    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue(null)}
        fetchRunDetail={fetchRunDetail}
        startRefresh={startRefresh}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "启动今日研究" }));
    expect(await screen.findByText("run-old")).toBeInTheDocument();

    // Close the first run dialog so the start control is available again.
    fireEvent.click(screen.getByRole("button", { name: "收起 Agent 进度" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agent 协作进度" })).not
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "启动今日研究" }));
    expect(await screen.findByText("run-new")).toBeInTheDocument();
    expect(screen.queryByText("run-old")).not.toBeInTheDocument();
  });

  it("shows the exact blocked node and retryable failure reason", async () => {
    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue({
          run_id: "run-blocked",
          state: "failed_retryable",
        })}
        fetchRunDetail={vi.fn().mockResolvedValue({
          ...baseRun,
          completed_count: 2,
          failed_count: 0,
          pending_count: 10,
          run_id: "run-blocked",
          status: "failed_retryable",
          steps: [
            { status: "succeeded", step: "DATA_FRESHNESS_CHECK" },
            { status: "succeeded", step: "DATA_SYNC" },
            { status: "succeeded", step: "SCOPE_RESOLVE" },
            { status: "succeeded", step: "QUANT_INPUT_BUILD" },
            { status: "succeeded", step: "QUANT_RUN" },
            {
              error_code: "news_refresh_incomplete",
              finished_at: "2026-07-01T04:12:00Z",
              started_at: "2026-07-01T04:05:00Z",
              status: "failed_retryable",
              step: "NEWS_REFRESH",
            },
          ],
        })}
      />,
    );

    expect(await screen.findByText("run-blocked")).toBeInTheDocument();
    expect(screen.getByTestId("agent-activity-news_acquisition")).toHaveAttribute(
      "data-agent-state",
      "waiting",
    );
    expect(screen.getByText("断点：news_refresh_incomplete")).toBeInTheDocument();
    expect(screen.getByText("状态：failed_retryable")).toBeInTheDocument();
  });

  it("allows users to collapse and reopen the latest run graph", async () => {
    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue({
          run_id: "run-latest",
          state: "running",
        })}
        fetchRunDetail={vi.fn().mockResolvedValue({
          ...baseRun,
          run_id: "run-latest",
          steps: [{ status: "succeeded", step: "DATA_FRESHNESS_CHECK" }],
        })}
      />,
    );

    expect(await screen.findByText("run-latest")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "收起 Agent 进度" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agent 协作进度" }))
        .not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "打开 Agent 进度" }));
    expect(screen.getByRole("dialog", { name: "Agent 协作进度" }))
      .toBeInTheDocument();
  });

  it("keeps a user-dismissed active run collapsed after remount", async () => {
    const latestRun = {
      run_id: "run-active",
      state: "running",
    };
    const runDetail = {
      ...baseRun,
      run_id: "run-active",
      steps: [{ status: "running", step: "DATA_SYNC" }],
    };
    const fetchLatestRun = vi.fn().mockResolvedValue(latestRun);
    const fetchRunDetail = vi.fn().mockResolvedValue(runDetail);

    const firstRender = renderControl(
      <DashboardRefreshControl
        fetchLatestRun={fetchLatestRun}
        fetchRunDetail={fetchRunDetail}
      />,
    );

    expect(await screen.findByText("run-active")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "收起 Agent 进度" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agent 协作进度" }))
        .not.toBeInTheDocument(),
    );

    firstRender.unmount();
    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={fetchLatestRun}
        fetchRunDetail={fetchRunDetail}
      />,
    );

    await screen.findByRole("button", { name: "打开 Agent 进度" });
    expect(screen.queryByRole("dialog", { name: "Agent 协作进度" }))
      .not.toBeInTheDocument();
  });

  it("closes the graph when users click the backdrop", async () => {
    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue({
          run_id: "run-latest",
          state: "running",
        })}
        fetchRunDetail={vi.fn().mockResolvedValue({
          ...baseRun,
          run_id: "run-latest",
          steps: [{ status: "succeeded", step: "DATA_FRESHNESS_CHECK" }],
        })}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: "Agent 协作进度",
    });
    // Backdrop is the dialog surface itself; clicking it (not the panel) closes.
    fireEvent.click(dialog);

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agent 协作进度" }))
        .not.toBeInTheDocument(),
    );
  });

  it("disables starting another refresh while the latest run is still active", async () => {
    const startRefresh = vi.fn().mockResolvedValue({
      http_status: 202,
      run_id: "run-new",
      status: "accepted",
    });

    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue({
          run_id: "run-active",
          state: "running",
        })}
        fetchRunDetail={vi.fn().mockResolvedValue({
          ...baseRun,
          run_id: "run-active",
          steps: [{ status: "running", step: "DATA_SYNC" }],
        })}
        startRefresh={startRefresh}
      />,
    );

    const button = await screen.findByRole("button", {
      name: "Agent 研究中",
    });
    expect(button).toBeDisabled();

    fireEvent.click(button);

    expect(startRefresh).not.toHaveBeenCalled();
  });

  it("refreshes dashboard data when the latest run reaches a terminal state", async () => {
    const startRefresh = vi.fn().mockResolvedValue({
      http_status: 202,
      run_id: "run-done",
      status: "accepted",
    });

    renderControl(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue(null)}
        fetchRunDetail={vi.fn().mockResolvedValue({
          ...baseRun,
          completed_count: 12,
          pending_count: 0,
          run_id: "run-done",
          status: "succeeded",
          steps: [{ status: "succeeded", step: "DASHBOARD_REFRESH" }],
        })}
        startRefresh={startRefresh}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "启动今日研究" }));

    await waitFor(() => expect(routerMocks.refresh).toHaveBeenCalledTimes(1));
  });
});

function renderControl(node: ReactElement) {
  return render(<LanguageProvider>{node}</LanguageProvider>);
}
