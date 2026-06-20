/**
 * @fileoverview Unit tests for the write/mutation helpers in `api.ts`.
 *
 * Verifies that POST payloads and endpoint paths are forwarded correctly to the
 * Margin backend using Vitest mocks.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createPositionReview,
  createResearchItemFeedback,
  createResearchRun,
  evaluatePositionMonitoring,
} from "./api";

/** Mock for `response.json()` shared across tests. */
const json = vi.fn();

describe("api mutation helpers", () => {
  beforeEach(() => {
    json.mockReset();
    json.mockResolvedValue({});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json,
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts a research run creation request to the backend", async () => {
    json.mockResolvedValueOnce({ run_id: "run_1" });

    await createResearchRun({
      strategy_id: "default",
      version_id: "v0.1",
      portfolio_id: "demo",
      symbols: ["000001.SZ", "600000.SH"],
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/research-runs",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        body: JSON.stringify({
          strategy_id: "default",
          version_id: "v0.1",
          portfolio_id: "demo",
          symbols: ["000001.SZ", "600000.SH"],
        }),
      }),
    );
  });

  it("posts deterministic position monitoring inputs", async () => {
    json.mockResolvedValueOnce({ position_id: "pos_1" });

    await evaluatePositionMonitoring("pos_1", {
      portfolio_id: "demo",
      current_price: 9.7,
      evidence_refs: ["ev_1"],
      model_rank_delta: -0.3,
      industry_exposure: 0.42,
      strategy_failure: true,
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/positions/pos_1/monitoring/evaluate",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        body: JSON.stringify({
          portfolio_id: "demo",
          current_price: 9.7,
          evidence_refs: ["ev_1"],
          model_rank_delta: -0.3,
          industry_exposure: 0.42,
          strategy_failure: true,
        }),
      }),
    );
  });

  it("posts a manual position review record", async () => {
    json.mockResolvedValueOnce({ review_id: "rv_1" });

    await createPositionReview("pos_1", {
      portfolio_id: "demo",
      alert_id: "al_1",
      decision: "reduce",
      rationale: "触发 P0 后降低仓位",
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/positions/pos_1/reviews",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        body: JSON.stringify({
          portfolio_id: "demo",
          alert_id: "al_1",
          decision: "reduce",
          rationale: "触发 P0 后降低仓位",
        }),
      }),
    );
  });

  it("posts research item feedback", async () => {
    json.mockResolvedValueOnce({ feedback_id: "fb_1" });

    await createResearchItemFeedback("item_1", {
      feedback_type: "reject",
      comment: "证据不足",
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/research-items/item_1/feedback",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        body: JSON.stringify({
          feedback_type: "reject",
          comment: "证据不足",
        }),
      }),
    );
  });
});
