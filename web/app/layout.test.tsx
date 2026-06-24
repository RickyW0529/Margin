/**
 * @fileoverview Tests for the global application shell.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RootLayout from "./layout";

vi.mock("@/components/admin-gate", () => ({
  AdminGate: () => <button type="button">未解锁</button>,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

describe("RootLayout", () => {
  it("renders only implemented top-level navigation targets", () => {
    render(
      <RootLayout>
        <div>页面内容</div>
      </RootLayout>,
    );

    const nav = screen.getByRole("navigation", { name: "主导航分组" });

    expect(within(nav).getByRole("link", { name: "工作台" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(within(nav).getByRole("link", { name: "研究候选" })).toHaveAttribute(
      "href",
      "/research",
    );
    expect(within(nav).getByRole("link", { name: "公司池" })).toHaveAttribute(
      "href",
      "/research/universe",
    );
    expect(within(nav).getByRole("link", { name: "刷新记录" })).toHaveAttribute(
      "href",
      "/research/runs",
    );
    expect(within(nav).getByRole("link", { name: "策略模板" })).toHaveAttribute(
      "href",
      "/strategies",
    );
    expect(
      within(nav).getByRole("link", { name: "Provider 密钥" }),
    ).toHaveAttribute("href", "/settings/providers");
    expect(within(nav).getByRole("link", { name: "数据策略" })).toHaveAttribute(
      "href",
      "/settings/data",
    );
    expect(within(nav).queryByRole("link", { name: "运行记录" })).toBeNull();
  });
});
