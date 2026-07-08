import type { ResearchRunDetailV2 } from "@/lib/api";

export type RefreshRunNodeState =
  | "active"
  | "completed"
  | "failed"
  | "pending"
  | "queued"
  | "waiting";

export type RefreshRunNode = {
  id: string;
  label: string;
  owner: string;
  state: RefreshRunNodeState;
  status: string;
  errorCode: string | null;
  startedAt: string | null;
  finishedAt: string | null;
};

type RefreshRunStepDefinition = {
  id: string;
  label: string;
  owner: string;
  aliases: string[];
};

export const REFRESH_RUN_STEPS = [
  {
    aliases: ["DATA_FRESHNESS_CHECK", "DATA_SYNC", "SCOPE_RESOLVE"],
    id: "data_inspection",
    label: "数据检查",
    owner: "DataInspectionAgent",
  },
  {
    aliases: ["QUANT_INPUT_BUILD", "QUANT_RUN"],
    id: "quant_analysis",
    label: "量化分析",
    owner: "QuantAgent",
  },
  {
    aliases: ["NEWS_TARGET_SELECTION", "NEWS_REFRESH", "NEWS_INDEXING"],
    id: "news_acquisition",
    label: "新闻/研报",
    owner: "NewsAcquisitionAgent",
  },
  {
    aliases: ["RESEARCH_CONTEXT_BUILD"],
    id: "evidence_context",
    label: "证据构建",
    owner: "StockAnalystAgent",
  },
  {
    aliases: ["AI_DELTA_REVIEW", "VALUATION_PUBLISH"],
    id: "stock_analysis",
    label: "综合分析",
    owner: "StockAnalystAgent",
  },
  {
    aliases: ["FINAL_REVIEW"],
    id: "main_agent_final_review",
    label: "主 Agent 复核",
    owner: "MainAgent",
  },
  {
    aliases: ["DASHBOARD_REFRESH"],
    id: "dashboard_publish",
    label: "Dashboard 发布",
    owner: "Dashboard",
  },
] as const satisfies readonly RefreshRunStepDefinition[];

const COMPLETED_STATES = new Set([
  "completed",
  "skipped",
  "succeeded",
  "succeeded_with_degradation",
]);
const FAILED_STATES = new Set(["cancelled", "failed_final", "upstream_failed"]);
const WAITING_STATES = new Set([
  "failed_retryable",
  "partial",
  "waiting_budget",
  "waiting_provider",
  "waiting_rate_limit",
  "waiting_retry",
]);
const TERMINAL_RUN_STATES = new Set([
  "cancelled",
  "failed_final",
  "skipped",
  "succeeded",
]);
const NON_POLLING_WAIT_STATES = new Set(["waiting_budget"]);

/** Returns true when a run is still expected to advance. */
export function isRefreshRunPollingState(status: string | null | undefined): boolean {
  const normalized = status ?? "";
  return (
    !TERMINAL_RUN_STATES.has(normalized) &&
    !NON_POLLING_WAIT_STATES.has(normalized)
  );
}

/** Returns true when a run has reached a terminal state. */
export function isRefreshRunTerminalState(
  status: string | null | undefined,
): boolean {
  return TERMINAL_RUN_STATES.has(status ?? "");
}

/** Builds a stable dashboard node graph from a sparse run status payload. */
export function buildRefreshRunNodes(
  run: ResearchRunDetailV2 | null,
): RefreshRunNode[] {
  const stepsById = new Map(
    (run?.steps ?? []).map((step) => [extractStepId(step), step]),
  );
  const nodes = REFRESH_RUN_STEPS.map((definition) =>
    buildRefreshRunNode(definition, stepsById, run),
  );

  if (
    run &&
    isRefreshRunPollingState(run.status) &&
    !nodes.some(
      (node) =>
        node.state === "active" ||
        node.state === "queued" ||
        node.state === "waiting",
    )
  ) {
    const nextNode = nodes.find((node) => node.state === "pending");
    if (nextNode) {
      nextNode.state = "active";
      nextNode.status = "pending";
    }
  }
  return nodes;
}

function buildRefreshRunNode(
  definition: RefreshRunStepDefinition,
  stepsById: Map<string, Record<string, unknown>>,
  run: ResearchRunDetailV2 | null,
): RefreshRunNode {
  const stepKeys = stepsById.has(definition.id)
    ? [definition.id]
    : definition.aliases;
  const steps = stepKeys
    .map((id) => stepsById.get(id))
    .filter((step): step is Record<string, unknown> => Boolean(step));

  if (steps.length === 0) {
    if (
      definition.id === "dashboard_publish" &&
      run &&
      COMPLETED_STATES.has(run.status)
    ) {
      return {
        errorCode: null,
        finishedAt: null,
        id: definition.id,
        label: definition.label,
        owner: definition.owner,
        startedAt: null,
        state: "completed",
        status: "published",
      };
    }
    return {
      errorCode: null,
      finishedAt: null,
      id: definition.id,
      label: definition.label,
      owner: definition.owner,
      startedAt: null,
      state: "pending",
      status: "pending",
    };
  }

  const classifiedSteps = steps.map((step) => {
    const status = text(step.status) || "pending";
    return {
      errorCode: nullableText(step.error_code),
      finishedAt: nullableText(step.finished_at),
      startedAt: nullableText(step.started_at),
      state: classifyStep(status, step),
      status,
    };
  });
  const state = summarizeState(classifiedSteps, steps.length, stepKeys.length);
  const activeStep =
    classifiedSteps.find((step) => step.state === state) ??
    classifiedSteps[classifiedSteps.length - 1];

  return {
    errorCode:
      classifiedSteps.find((step) => step.errorCode)?.errorCode ?? null,
    finishedAt: latestText(classifiedSteps.map((step) => step.finishedAt)),
    id: definition.id,
    label: definition.label,
    owner: definition.owner,
    startedAt: earliestText(classifiedSteps.map((step) => step.startedAt)),
    state,
    status:
      state === "completed"
        ? `${classifiedSteps.length}/${stepKeys.length} completed`
        : activeStep.status,
  };
}

function summarizeState(
  steps: Array<{ state: RefreshRunNodeState }>,
  matchedCount: number,
  expectedCount: number,
): RefreshRunNodeState {
  if (steps.some((step) => step.state === "failed")) {
    return "failed";
  }
  if (steps.some((step) => step.state === "waiting")) {
    return "waiting";
  }
  if (steps.some((step) => step.state === "active")) {
    return "active";
  }
  if (steps.some((step) => step.state === "queued")) {
    return "queued";
  }
  if (
    matchedCount === expectedCount &&
    steps.every((step) => step.state === "completed")
  ) {
    return "completed";
  }
  if (steps.some((step) => step.state === "completed")) {
    return "active";
  }
  return "pending";
}

function classifyStep(
  status: string,
  step: Record<string, unknown> | undefined,
): RefreshRunNodeState {
  if (!step) {
    return "pending";
  }
  if (text(step.error_code) === "upstream_failed") {
    return "failed";
  }
  if (COMPLETED_STATES.has(status)) {
    return "completed";
  }
  if (FAILED_STATES.has(status)) {
    return "failed";
  }
  if (WAITING_STATES.has(status)) {
    return "waiting";
  }
  if (status === "running") {
    return "active";
  }
  if (status === "pending" && step.started_at) {
    return "queued";
  }
  return "pending";
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function nullableText(value: unknown): string | null {
  const normalized = text(value);
  return normalized ? normalized : null;
}

function extractStepId(step: Record<string, unknown>): string {
  return text(step.step_id) || text(step.step);
}

function earliestText(values: Array<string | null>): string | null {
  return values.filter((value): value is string => Boolean(value)).sort()[0] ?? null;
}

function latestText(values: Array<string | null>): string | null {
  const sorted = values.filter((value): value is string => Boolean(value)).sort();
  return sorted[sorted.length - 1] ?? null;
}
