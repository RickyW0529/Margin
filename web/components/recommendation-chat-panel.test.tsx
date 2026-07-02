/**
 * @fileoverview Tests for the user-facing recommendation chat panel.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecommendationChatPanel } from "./recommendation-chat-panel";

afterEach(cleanup);

describe("RecommendationChatPanel", () => {
  it("asks the baseline recommendation question through the read-only tool", async () => {
    const ask = vi.fn().mockResolvedValue({
      answer: "今日推荐关注 000001、600000。",
      references: [{ api: "GET /api/v1/research", scope_version_id: "scope-current" }],
    });

    render(<RecommendationChatPanel ask={ask} />);

    fireEvent.click(screen.getByRole("button", { name: "今日推荐股票是什么？" }));

    await waitFor(() =>
      expect(ask).toHaveBeenCalledWith({
        message: "今日推荐股票是什么？",
        scope_version_id: "scope-current",
        universe: "ALL_A",
      }),
    );
    expect(screen.getByText("今日推荐关注 000001、600000。")).toBeInTheDocument();
    expect(screen.getByText("推荐列表")).toBeInTheDocument();
    expect(screen.queryByText("GET /api/v1/research")).not.toBeInTheDocument();
  });
});
