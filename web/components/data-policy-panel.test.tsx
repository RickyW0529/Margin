/**
 * @fileoverview Rolling-window data policy settings tests.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { DataPolicyPanel } from "./data-policy-panel";

afterEach(cleanup);

const activePolicy = {
  version_id: "data-policy-24",
  owner_id: "local-admin",
  rolling_window_months: 24,
  revision_lookback_days: 30,
  financial_comparison_years: 1,
  lifecycle: "active",
  config_hash: "sha256:24",
  created_at: "2026-06-23T10:00:00Z",
  activated_at: "2026-06-23T10:01:00Z",
  window_start: "2024-06-23T00:00:00Z",
  window_end: "2026-06-23T10:00:00Z",
};

test("data policy creates a version and exposes activation separately", async () => {
  const createPolicy = vi.fn().mockResolvedValue({
    ...activePolicy,
    version_id: "data-policy-36",
    rolling_window_months: 36,
    lifecycle: "draft",
    window_start: "2023-06-23T00:00:00Z",
  });
  const activatePolicy = vi.fn().mockResolvedValue({
    ...activePolicy,
    version_id: "data-policy-36",
    rolling_window_months: 36,
  });

  render(
    <DataPolicyPanel
      initialPolicies={{
        active_version_id: activePolicy.version_id,
        versions: [activePolicy],
      }}
      createPolicy={createPolicy}
      activatePolicy={activatePolicy}
      triggerSync={vi.fn()}
    />,
  );

  expect(screen.getByText("24 个月")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("滚动数据窗口（月）"), {
    target: { value: "36" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

  await waitFor(() =>
    expect(createPolicy).toHaveBeenCalledWith({
      financial_comparison_years: 1,
      revision_lookback_days: 30,
      rolling_window_months: 36,
    }),
  );
  expect(screen.getByText("新版本已保存，激活后才会影响后续同步。")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "激活 36 个月版本" }));
  await waitFor(() => expect(activatePolicy).toHaveBeenCalledWith("data-policy-36"));
  expect(screen.getByText("36 个月")).toBeInTheDocument();
});

test("data policy blocks invalid frontend window before request", () => {
  const createPolicy = vi.fn();
  render(
    <DataPolicyPanel
      initialPolicies={{
        active_version_id: activePolicy.version_id,
        versions: [activePolicy],
      }}
      createPolicy={createPolicy}
      activatePolicy={vi.fn()}
      triggerSync={vi.fn()}
    />,
  );

  fireEvent.change(screen.getByLabelText("滚动数据窗口（月）"), {
    target: { value: "61" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));

  expect(screen.getByRole("alert")).toHaveTextContent("12 到 60 个月");
  expect(createPolicy).not.toHaveBeenCalled();
});
