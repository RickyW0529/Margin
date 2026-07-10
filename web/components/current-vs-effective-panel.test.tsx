/**
 * @fileoverview Tests for the current-vs-effective assessment panel.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "@/lib/i18n";

import { CurrentVsEffectivePanel } from "./current-vs-effective-panel";

afterEach(() => {
  cleanup();
});

describe("CurrentVsEffectivePanel", () => {
  it("distinguishes deferred current review from a stale effective thesis", () => {
    render(
      <LanguageProvider>
        <CurrentVsEffectivePanel
          currentReview={{
            outcome: "review_deferred",
            reason: "news_target_incomplete",
          }}
          effectiveAssessment={{
            freshness: "stale",
          }}
        />
      </LanguageProvider>,
    );

    expect(screen.getByText("本轮复核：延期")).toBeInTheDocument();
    expect(screen.getByText("当前有效结论：已过期")).toBeInTheDocument();
    expect(
      screen.getByText("本轮复核所需新闻尚未齐全。"),
    ).toBeInTheDocument();
  });
});
