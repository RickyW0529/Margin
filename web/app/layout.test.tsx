/**
 * @fileoverview Tests for the global application shell.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RootLayout from "./layout";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

describe("RootLayout", () => {
  it("renders a simplified user-facing navigation", () => {
    render(
      <RootLayout>
        <div>页面内容</div>
      </RootLayout>,
    );

    const nav = screen.getByRole("navigation", { name: "主导航分组" });

    expect(within(nav).getByRole("link", { name: "问答" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(within(nav).getByRole("link", { name: "今日推荐" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(within(nav).getByRole("link", { name: "设置" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(within(nav).queryByRole("link", { name: "研究候选" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Provider 密钥" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "数据策略" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "策略模板" })).toBeNull();
    expect(screen.queryByRole("button", { name: "未解锁" })).toBeNull();
  });
});
