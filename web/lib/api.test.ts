/**
 * @fileoverview Unit tests for the write/mutation helpers in `api.ts`.
 *
 * Verifies that POST payloads and endpoint paths are forwarded correctly to the
 * Margin backend using Vitest mocks.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateDataPolicy,
  createProviderConfig,
  createDataPolicy,
  createResearchItemFeedback,
  fetchProviderConfigs,
  fetchProviderStatus,
  fetchQuantStrategyDefaults,
  fetchResearchCandidates,
  fetchResearchRunDetailV2,
  fetchValuationDiscoveryRuns,
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

  it("posts a valuation-discovery refresh with local idempotency", async () => {
    json.mockResolvedValueOnce({ run_id: "run_1", status: "pending" });
    vi.stubGlobal("crypto", { randomUUID: () => "idempotency-1" });

    await startValuationDiscoveryRefresh({
      decision_at: "2026-06-23T08:30:00.000Z",
      scope_version_id: "scope-1",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/valuation-discovery/refreshes",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          "Idempotency-Key": "idempotency-1",
        }),
        body: JSON.stringify({
          decision_at: "2026-06-23T08:30:00.000Z",
          scope_version_id: "scope-1",
        }),
      }),
    );
  });

  it("uses same-origin API paths for browser provider mutations", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => "provider-create-idem" });

    await createProviderConfig({
      base_url: "https://api.minimaxi.com/v1",
      provider_name: "llm",
      provider_type: "llm",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/provider-configs",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          "Idempotency-Key": "provider-create-idem",
        }),
      }),
    );
  });

  it("ignores public API base URLs in browser builds", async () => {
    process.env.NEXT_PUBLIC_MARGIN_API_BASE_URL = "http://127.0.0.1:8000";
    vi.stubGlobal("crypto", { randomUUID: () => "provider-public-env-idem" });

    await createProviderConfig({
      base_url: "https://api.minimaxi.com/v1",
      provider_name: "llm",
      provider_type: "llm",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/provider-configs",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Idempotency-Key": "provider-public-env-idem",
        }),
      }),
    );
  });

  it("falls back to a local idempotency key when randomUUID is unavailable", async () => {
    vi.stubGlobal("crypto", {});

    await createProviderConfig({
      base_url: "https://api.minimaxi.com/v1",
      provider_name: "llm",
      provider_type: "llm",
    });

    const headers = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1]
      .headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/^idem-/);
  });

  it("posts research item feedback", async () => {
    json.mockResolvedValueOnce({ feedback_id: "fb_1" });
    vi.stubGlobal("crypto", { randomUUID: () => "feedback-idem" });

    await createResearchItemFeedback("item_1", {
      feedback_type: "reject",
      comment: "证据不足",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/research-items/item_1/feedback",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          "Idempotency-Key": "feedback-idem",
        }),
        body: JSON.stringify({
          feedback_type: "reject",
          comment: "证据不足",
        }),
      }),
    );
  });

  it("creates and activates rolling data policy versions", async () => {
    json.mockResolvedValue({});
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
      "/api/v1/data-policies",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "policy-create-idem",
        }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/data-policies/data-policy-24/activate",
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
      "/api/v1/research?scope_version_id=scope-1&universe=HS300&limit=25&screening_status=pass&data_status=complete&review_required=true",
      expect.objectContaining({
        next: { revalidate: 30 },
      }),
    );
  });

  it("fetches built-in quant strategy defaults", async () => {
    json.mockResolvedValueOnce({ presets: {} });

    await fetchQuantStrategyDefaults();

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/quant-strategy-defaults",
      expect.objectContaining({
        next: { revalidate: 30 },
      }),
    );
  });

  it("fetches provider configs and status without stale revalidation", async () => {
    json.mockResolvedValue([]);

    await fetchProviderConfigs();
    await fetchProviderStatus();

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/provider-configs",
      expect.objectContaining({
        cache: "no-store",
      }),
    );
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1]).not.toHaveProperty("next");
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/provider-status",
      expect.objectContaining({
        cache: "no-store",
      }),
    );
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[1][1]).not.toHaveProperty("next");
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
          state: "waiting_budget",
          step_id: "NEWS_REFRESH",
        },
      ],
    });

    const detail = await fetchResearchRunDetailV2("vdr-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/valuation-discovery/runs/vdr-1",
      expect.objectContaining({
        cache: "no-store",
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
      wait_state: "waiting_budget",
    });
    expect(detail.steps[0]).toMatchObject({
      error_code: null,
      status: "succeeded",
      step: "QUANT_RUN",
    });
  });

  it("fetches recent valuation refresh runs without cache for dashboard polling", async () => {
    json.mockResolvedValueOnce({
      items: [],
      next_cursor: null,
      page_size: 1,
    });

    await fetchValuationDiscoveryRuns({
      limit: 1,
      scope_version_id: "scope-current",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/valuation-discovery/runs?scope_version_id=scope-current&limit=1",
      expect.objectContaining({
        cache: "no-store",
      }),
    );
  });
});
