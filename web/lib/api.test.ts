/**
 * @fileoverview Unit tests for the write/mutation helpers in `api.ts`.
 *
 * Verifies that POST payloads and endpoint paths are forwarded correctly to the
 * Margin backend using Vitest mocks.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateDataPolicy,
  createDataPolicy,
  createResearchItemFeedback,
  fetchQuantStrategyDefaults,
  fetchResearchCandidates,
  fetchResearchRunDetailV2,
  startValuationDiscoveryRefresh,
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

  it("posts a valuation-discovery refresh with local admin headers", async () => {
    json.mockResolvedValueOnce({ run_id: "run_1", status: "pending" });
    window.localStorage.setItem("margin.adminApiToken", "admin-token");
    window.localStorage.setItem("margin.csrfToken", "csrf-token");
    vi.stubGlobal("crypto", { randomUUID: () => "idempotency-1" });

    await startValuationDiscoveryRefresh({
      decision_at: "2026-06-23T08:30:00.000Z",
      scope_version_id: "scope-1",
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/valuation-discovery/refreshes",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer admin-token",
          "Idempotency-Key": "idempotency-1",
          "X-CSRF-Token": "csrf-token",
        }),
        body: JSON.stringify({
          decision_at: "2026-06-23T08:30:00.000Z",
          scope_version_id: "scope-1",
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

  it("creates and activates rolling data policy versions", async () => {
    json.mockResolvedValue({});
    window.localStorage.setItem("margin.adminApiToken", "admin-token");
    window.localStorage.setItem("margin.csrfToken", "csrf-token");
    vi.stubGlobal("crypto", {
      randomUUID: vi
        .fn()
        .mockReturnValueOnce("policy-create-idem")
        .mockReturnValueOnce("policy-activate-idem"),
    });

    await createDataPolicy({
      financial_comparison_years: 1,
      revision_lookback_days: 30,
      rolling_window_months: 24,
    });
    await activateDataPolicy("data-policy-24");

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/api/v1/data-policies",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer admin-token",
          "Idempotency-Key": "policy-create-idem",
          "X-CSRF-Token": "csrf-token",
        }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/v1/data-policies/data-policy-24/activate",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "policy-activate-idem",
        }),
      }),
    );
  });

  it("fetches v0.2 research candidates with server-side filters", async () => {
    json.mockResolvedValueOnce({ items: [], page_info: { has_next_page: false } });

    await fetchResearchCandidates({
      data_status: "complete",
      limit: 25,
      review_required: "true",
      scope_version_id: "scope-1",
      screening_status: "pass",
      universe: "HS300",
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/research?scope_version_id=scope-1&universe=HS300&limit=25&screening_status=pass&data_status=complete&review_required=true",
      expect.objectContaining({
        next: { revalidate: 30 },
      }),
    );
  });

  it("fetches built-in quant strategy defaults", async () => {
    json.mockResolvedValueOnce({ presets: {} });

    await fetchQuantStrategyDefaults();

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/quant-strategy-defaults",
      expect.objectContaining({
        next: { revalidate: 30 },
      }),
    );
  });

  it("maps valuation-discovery run status into research progress detail", async () => {
    json.mockResolvedValueOnce({
      run_id: "vdr-1",
      scope_version_id: "scope-1",
      state: "running",
      steps: [
        {
          attempt_no: 1,
          error_code: null,
          finished_at: "2026-06-23T08:31:00Z",
          output_ref: "quant_run_1",
          started_at: "2026-06-23T08:30:00Z",
          state: "succeeded",
          step_id: "QUANT_RUN",
        },
        {
          attempt_no: 1,
          error_code: "provider_budget_exceeded",
          finished_at: null,
          output_ref: null,
          started_at: "2026-06-23T08:32:00Z",
          state: "waiting_provider",
          step_id: "NEWS_REFRESH",
        },
      ],
    });

    const detail = await fetchResearchRunDetailV2("vdr-1");

    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/valuation-discovery/runs/vdr-1",
      expect.objectContaining({
        next: { revalidate: 30 },
      }),
    );
    expect(detail).toMatchObject({
      completed_count: 1,
      failed_count: 0,
      pending_count: 1,
      run_id: "vdr-1",
      status: "running",
      target_count: 2,
      trace_id: "vdr-1",
      wait_state: "waiting_provider",
    });
    expect(detail.steps[0]).toMatchObject({
      error_code: null,
      status: "succeeded",
      step: "QUANT_RUN",
    });
  });
});
