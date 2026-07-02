/**
 * @fileoverview Tests for the settings hub page.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SettingsPage from "./page";

describe("SettingsPage", () => {
  it("links to advanced configuration subpages", () => {
    render(<SettingsPage />);

    expect(screen.getByRole("heading", { name: "设置" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /密钥配置/ })).toHaveAttribute(
      "href",
      "/settings/providers",
    );
    expect(screen.getByRole("link", { name: /数据配置/ })).toHaveAttribute(
      "href",
      "/settings/data",
    );
    expect(screen.getByRole("link", { name: /研究范围/ })).toHaveAttribute(
      "href",
      "/settings/scope",
    );
    expect(screen.getByRole("link", { name: /策略配置/ })).toHaveAttribute(
      "href",
      "/settings/strategy",
    );
  });
});
