import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MarkdownContent } from "./markdown-content";

afterEach(cleanup);

describe("MarkdownContent", () => {
  it("renders headings, lists, and GFM tables as semantic elements", () => {
    render(
      <MarkdownContent
        content={[
          "### 回答",
          "",
          "- 最近四期 ROE",
          "",
          "| 期末 | ROE |",
          "| --- | ---: |",
          "| 2026Q1 | 12.3% |",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("heading", { name: "回答", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByText("### 回答")).toBeNull();
  });

  it("does not render raw HTML from model output", () => {
    const { container } = render(
      <MarkdownContent content={'<script>alert("x")</script><b>unsafe</b>'} />,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("keeps fenced code readable on the dark code surface", () => {
    const { container } = render(
      <MarkdownContent content={'```json\n{"roe": 12.3}\n```'} />,
    );

    expect(container.querySelector("pre code")).toHaveClass("text-background");
  });
});
