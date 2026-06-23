/**
 * @fileoverview Tests for read-only Copilot panel.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReadOnlyCopilotPanel } from "./read-only-copilot-panel";

afterEach(() => {
  cleanup();
});

describe("ReadOnlyCopilotPanel", () => {
  it("answers using read-only references", async () => {
    const ask = vi.fn().mockResolvedValue({
      answer: "当前可以继续看 000001。",
      references: [{ api: "GET /api/v1/research", scope_version_id: "scope-1" }],
    });

    render(<ReadOnlyCopilotPanel ask={ask} scopeVersionId="scope-1" />);

    fireEvent.change(screen.getByLabelText("只读问题"), {
      target: { value: "今天哪些公司值得继续看" },
    });
    fireEvent.click(screen.getByRole("button", { name: "询问只读 Copilot" }));

    await waitFor(() => expect(ask).toHaveBeenCalled());
    expect(screen.getByText("当前可以继续看 000001。")).toBeInTheDocument();
    expect(screen.getByText("GET /api/v1/research")).toBeInTheDocument();
  });
});
