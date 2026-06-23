/**
 * @fileoverview Tests for the current-vs-effective assessment panel.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CurrentVsEffectivePanel } from "./current-vs-effective-panel";

afterEach(() => {
  cleanup();
});

describe("CurrentVsEffectivePanel", () => {
  it("distinguishes deferred current review from valid carry-forward", () => {
    render(
      <CurrentVsEffectivePanel
        currentReview={{
          outcome: "review_deferred",
          reason: "news_target_incomplete",
        }}
        effectiveAssessment={{
          assessment_id: "assess-old",
          freshness: "stale",
        }}
      />,
    );

    expect(screen.getByText("本轮复核：延期")).toBeInTheDocument();
    expect(screen.getByText("当前有效结论：assess-old")).toBeInTheDocument();
    expect(screen.getByText("news_target_incomplete")).toBeInTheDocument();
  });
});
