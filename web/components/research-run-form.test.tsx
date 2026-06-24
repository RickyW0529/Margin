/**
 * @fileoverview Research run form tests for the v0.2 valuation refresh flow.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResearchRunForm } from "./research-run-form";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  push.mockReset();
});

describe("ResearchRunForm", () => {
  it("starts a valuation refresh by scope and navigates to the run page", async () => {
    const startRefresh = vi.fn().mockResolvedValue({
      run_id: "run-v02",
      status: "pending",
      http_status: 202,
    });

    render(<ResearchRunForm startRefresh={startRefresh} />);
    fireEvent.change(screen.getByLabelText("研究作用域版本"), {
      target: { value: "scope-active" },
    });
    fireEvent.click(screen.getByRole("button", { name: "启动估值发现" }));

    await waitFor(() => expect(startRefresh).toHaveBeenCalled());
    expect(startRefresh).toHaveBeenCalledWith(
      expect.objectContaining({
        scope_version_id: "scope-active",
      }),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/research/runs/run-v02"));
  });

  it("surfaces missing local admin session errors", async () => {
    const startRefresh = vi
      .fn()
      .mockRejectedValue(new Error("Local admin session is not configured"));

    render(<ResearchRunForm startRefresh={startRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: "启动估值发现" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "请先在右上角解锁管理员模式",
    );
  });

  it("surfaces service configuration blockers from the API", async () => {
    const startRefresh = vi
      .fn()
      .mockRejectedValue(
        new Error(
          'Margin API 503: /api/v1/valuation-discovery/refreshes - {"detail":{"code":"service_not_configured","message":"active provider config not found: tavily"}}',
        ),
      );

    render(<ResearchRunForm startRefresh={startRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: "启动估值发现" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Tavily Provider 未激活",
    );
  });
});
