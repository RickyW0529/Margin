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
import type { ComponentType } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ResearchRunDetailV2 } from "@/lib/api";

import { DashboardRefreshControl } from "./dashboard-refresh-control";

const routerMocks = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerMocks.refresh,
  }),
}));

vi.mock("@xyflow/react", () => ({
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  Controls: () => null,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
  Position: { Left: "left", Right: "right" },
  ReactFlow: ({
    nodes,
    nodeTypes,
  }: {
    nodes: Array<{ data: unknown; id: string; type?: string }>;
    nodeTypes: Record<string, ComponentType<{ data: unknown }>>;
  }) => (
    <div data-testid="react-flow">
      {nodes.map((node) => {
        const NodeComponent = nodeTypes[node.type ?? ""];
        return NodeComponent ? (
          <NodeComponent data={node.data} key={node.id} />
        ) : null;
      })}
    </div>
  ),
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

    render(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue(null)}
        fetchRunDetail={fetchRunDetail}
        now={() => new Date("2026-07-01T04:00:00.000Z")}
        startRefresh={startRefresh}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "刷新今日研究" }));

    const dialog = await screen.findByRole("dialog", {
      name: "最近一次刷新节点图",
    });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveClass("fixed");
    expect(screen.getByText("run-1")).toBeInTheDocument();
    expect(screen.getByTestId("refresh-node-DATA_FRESHNESS_CHECK")).toHaveAttribute(
      "data-node-state",
      "completed",
    );
    expect(screen.getByTestId("refresh-node-DATA_SYNC")).toHaveAttribute(
      "data-node-state",
      "queued",
    );
    expect(screen.getByTestId("refresh-node-DATA_SYNC")).not.toHaveClass(
      "animate-pulse",
    );
    expect(screen.getByTestId("refresh-node-QUANT_RUN")).toHaveAttribute(
      "data-node-state",
      "pending",
    );
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

    render(
      <DashboardRefreshControl
        fetchLatestRun={vi.fn().mockResolvedValue(null)}
        fetchRunDetail={fetchRunDetail}
        startRefresh={startRefresh}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "刷新今日研究" }));
    expect(await screen.findByText("run-old")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "刷新今日研究" }));
    expect(await screen.findByText("run-new")).toBeInTheDocument();
    expect(screen.queryByText("run-old")).not.toBeInTheDocument();
  });

  it("allows users to collapse and reopen the latest run graph", async () => {
    render(
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
    fireEvent.click(screen.getByRole("button", { name: "收起节点图" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "最近一次刷新节点图" }))
        .not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "打开节点图" }));
    expect(screen.getByRole("dialog", { name: "最近一次刷新节点图" }))
      .toBeInTheDocument();
  });

  it("disables starting another refresh while the latest run is still active", async () => {
    const startRefresh = vi.fn().mockResolvedValue({
      http_status: 202,
      run_id: "run-new",
      status: "accepted",
    });

    render(
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
      name: "刷新进行中",
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

    render(
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

    fireEvent.click(screen.getByRole("button", { name: "刷新今日研究" }));

    await waitFor(() => expect(routerMocks.refresh).toHaveBeenCalledTimes(1));
  });
});
