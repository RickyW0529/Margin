/**
 * @fileoverview Tests for refresh run graph state classification.
 */

import { describe, expect, it } from "vitest";

import { buildRefreshRunNodes } from "./refresh-run-graph";

describe("buildRefreshRunNodes", () => {
  it("marks upstream-failed steps as failed instead of completed", () => {
    const nodes = buildRefreshRunNodes({
      completed_count: 1,
      failed_count: 1,
      pending_count: 10,
      retry_after_seconds: null,
      run_id: "run-1",
      status: "failed_final",
      steps: [
        { status: "succeeded", step: "DATA_FRESHNESS_CHECK" },
        { status: "upstream_failed", step: "QUANT_INPUT_BUILD" },
      ],
      supported_wait_states: [],
      target_count: 12,
      trace_id: "run-1",
      wait_state: null,
    });

    expect(
      nodes.find((node) => node.id === "QUANT_INPUT_BUILD"),
    ).toMatchObject({
      state: "failed",
      status: "upstream_failed",
    });
  });

  it("marks skipped steps with upstream_failed error code as failed", () => {
    const nodes = buildRefreshRunNodes({
      completed_count: 1,
      failed_count: 1,
      pending_count: 10,
      retry_after_seconds: null,
      run_id: "run-1",
      status: "failed_final",
      steps: [
        { status: "failed_final", step: "SCOPE_RESOLVE" },
        {
          error_code: "upstream_failed",
          status: "skipped",
          step: "QUANT_INPUT_BUILD",
        },
      ],
      supported_wait_states: [],
      target_count: 12,
      trace_id: "run-1",
      wait_state: null,
    });

    expect(
      nodes.find((node) => node.id === "QUANT_INPUT_BUILD"),
    ).toMatchObject({
      errorCode: "upstream_failed",
      state: "failed",
      status: "skipped",
    });
  });

  it("marks scheduled pending steps as queued instead of active", () => {
    const nodes = buildRefreshRunNodes({
      completed_count: 1,
      failed_count: 0,
      pending_count: 11,
      retry_after_seconds: null,
      run_id: "run-1",
      status: "running",
      steps: [
        { status: "succeeded", step: "DATA_FRESHNESS_CHECK" },
        {
          started_at: "2026-07-01T10:49:24Z",
          status: "pending",
          step: "QUANT_INPUT_BUILD",
        },
      ],
      supported_wait_states: [],
      target_count: 12,
      trace_id: "run-1",
      wait_state: null,
    });

    expect(
      nodes.find((node) => node.id === "QUANT_INPUT_BUILD"),
    ).toMatchObject({
      state: "queued",
      status: "pending",
    });
    expect(nodes.some((node) => node.state === "active")).toBe(false);
  });
});
