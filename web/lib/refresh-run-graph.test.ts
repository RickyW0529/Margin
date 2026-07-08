/**
 * @fileoverview Tests for refresh run graph state classification.
 */

import { describe, expect, it } from "vitest";

import {
  buildRefreshRunNodes,
  isRefreshRunPollingState,
} from "./refresh-run-graph";

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
      nodes.find((node) => node.id === "quant_analysis"),
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
      nodes.find((node) => node.id === "quant_analysis"),
    ).toMatchObject({
      errorCode: "upstream_failed",
      state: "failed",
      status: "skipped",
    });
  });

  it("keeps queued Agent nodes distinct from partial active Agent nodes", () => {
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
      nodes.find((node) => node.id === "quant_analysis"),
    ).toMatchObject({
      state: "queued",
      status: "pending",
    });
    expect(nodes.find((node) => node.id === "data_inspection")).toMatchObject({
      state: "active",
    });
  });

  it("uses agent-runtime step ids as already aggregated Agent nodes", () => {
    const nodes = buildRefreshRunNodes({
      completed_count: 1,
      failed_count: 0,
      pending_count: 4,
      retry_after_seconds: null,
      run_id: "agent-run-1",
      status: "running",
      steps: [
        {
          finished_at: "2026-07-01T10:51:24Z",
          started_at: "2026-07-01T10:49:24Z",
          status: "succeeded",
          step_id: "data_inspection",
        },
      ],
      supported_wait_states: [],
      target_count: 5,
      trace_id: "agent-run-1",
      wait_state: null,
    });

    expect(nodes.find((node) => node.id === "data_inspection")).toMatchObject({
      owner: "DataInspectionAgent",
      state: "completed",
      status: "1/1 completed",
    });
    expect(nodes.find((node) => node.id === "quant_analysis")).toMatchObject({
      owner: "QuantAgent",
      state: "active",
    });
  });
});

describe("isRefreshRunPollingState", () => {
  it("does not poll indefinitely when a provider budget blocks the run", () => {
    expect(isRefreshRunPollingState("waiting_budget")).toBe(false);
  });

  it("continues polling retryable wait states", () => {
    expect(isRefreshRunPollingState("waiting_rate_limit")).toBe(true);
    expect(isRefreshRunPollingState("waiting_retry")).toBe(true);
  });
});
