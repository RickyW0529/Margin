/**
 * @fileoverview Company pool selector tests.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompanyPoolSelector } from "./company-pool-selector";

const routerMocks = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerMocks.refresh,
  }),
}));

afterEach(() => {
  cleanup();
  routerMocks.refresh.mockClear();
});

describe("CompanyPoolSelector", () => {
  it("renders the default pools and switches to a real configured pool", async () => {
    const activateConfig = vi.fn().mockResolvedValue({
      version_id: "universe-csi500-default-v0.3.0",
    });

    render(
      <CompanyPoolSelector
        activateConfig={activateConfig}
        scopes={[
          {
            lifecycle: "active",
            universe_version_id: "universe-all-a-default-v0.2.0",
            version_id: "scope-current",
          },
        ]}
        universes={[
          universe("universe-csi500-default-v0.3.0", "CSI500", "中证500", 500),
          universe("universe-all-a-default-v0.2.0", "ALL_A", "全 A", 5532),
          universe("universe-csi300-default-v0.3.0", "CSI300", "沪深300", 300),
        ]}
      />,
    );

    expect(screen.getByText("中证500")).toBeInTheDocument();
    expect(screen.getByText("全 A")).toBeInTheDocument();
    expect(screen.getByText("沪深300")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("company-pool-ALL_A")).getByRole("button", {
        name: "切换到全 A",
      }),
    ).toBeDisabled();

    const csi500Card = screen.getByTestId("company-pool-CSI500");
    expect(within(csi500Card).getByText("500 只")).toBeInTheDocument();
    fireEvent.click(within(csi500Card).getByRole("button", { name: "切换到中证500" }));

    await waitFor(() => expect(activateConfig).toHaveBeenCalled());
    expect(activateConfig).toHaveBeenCalledWith(
      "universe-configs",
      "universe-csi500-default-v0.3.0",
    );
    expect(routerMocks.refresh).toHaveBeenCalled();
  });

  it("keeps unavailable default pools disabled until they have real members", () => {
    render(
      <CompanyPoolSelector
        activateConfig={vi.fn()}
        scopes={[
          {
            lifecycle: "active",
            universe_version_id: "universe-all-a-default-v0.2.0",
            version_id: "scope-current",
          },
        ]}
        universes={[universe("universe-all-a-default-v0.2.0", "ALL_A", "全 A", 5532)]}
      />,
    );

    const csi300Card = screen.getByTestId("company-pool-CSI300");
    expect(within(csi300Card).getAllByText("等待数据同步").length).toBeGreaterThan(0);
    expect(within(csi300Card).getByRole("button", { name: "切换到沪深300" }))
      .toBeDisabled();
  });
});

function universe(
  versionId: string,
  universeCode: string,
  name: string,
  memberCount: number,
) {
  return {
    lifecycle: universeCode === "ALL_A" ? "active" : "review",
    member_security_ids: Array.from(
      { length: memberCount },
      (_, index) => `${String(index + 1).padStart(6, "0")}.SZ`,
    ),
    name,
    universe_code: universeCode,
    version_id: versionId,
  };
}
