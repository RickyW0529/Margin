/**
 * @fileoverview Tests for the v0.2 research filter bar.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ResearchFilterBar } from "./research-filter-bar";

afterEach(() => {
  cleanup();
});

describe("ResearchFilterBar", () => {
  it("renders server-side GET filters without secret inputs", () => {
    render(
      <ResearchFilterBar
        defaultValues={{
          data_status: "complete",
          review_required: "true",
          scope_version_id: "scope-1",
          screening_status: "pass",
          universe: "HS300",
        }}
      />,
    );

    expect(screen.getByLabelText("Scope 版本")).toHaveValue("scope-1");
    expect(screen.getByLabelText("公司池")).toHaveValue("HS300");
    expect(screen.getByLabelText("量化状态")).toHaveValue("pass");
    expect(screen.getByLabelText("数据状态")).toHaveValue("complete");
    expect(screen.getByLabelText("复核要求")).toHaveValue("true");

    fireEvent.change(screen.getByLabelText("公司池"), {
      target: { value: "CSI500" },
    });

    expect(screen.getByLabelText("公司池")).toHaveValue("CSI500");
    expect(screen.getByRole("button", { name: "应用筛选" })).toHaveAttribute(
      "type",
      "submit",
    );
    expect(screen.queryByLabelText(/secret|token|密钥/i)).not.toBeInTheDocument();
  });
});
