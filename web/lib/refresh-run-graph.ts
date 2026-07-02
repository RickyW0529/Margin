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
  state: RefreshRunNodeState;
  status: string;
  errorCode: string | null;
  startedAt: string | null;
  finishedAt: string | null;
};

export const REFRESH_RUN_STEPS = [
  ["DATA_FRESHNESS_CHECK", "数据新鲜度"],
  ["DATA_SYNC", "数据同步"],
  ["SCOPE_RESOLVE", "范围解析"],
  ["QUANT_INPUT_BUILD", "量化输入"],
  ["QUANT_RUN", "量化筛选"],
  ["NEWS_TARGET_SELECTION", "新闻目标"],
  ["NEWS_REFRESH", "新闻获取"],
  ["NEWS_INDEXING", "文本入库"],
  ["RESEARCH_CONTEXT_BUILD", "证据上下文"],
  ["AI_DELTA_REVIEW", "AI 复核"],
  ["VALUATION_PUBLISH", "结果发布"],
  ["DASHBOARD_REFRESH", "看板刷新"],
] as const;

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

/** Returns true when a run is still expected to advance. */
export function isRefreshRunPollingState(status: string | null | undefined): boolean {
  return !TERMINAL_RUN_STATES.has(status ?? "");
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
    (run?.steps ?? []).map((step) => [text(step.step), step]),
  );
  const nodes = REFRESH_RUN_STEPS.map(([id, label]) => {
    const step = stepsById.get(id);
    const status = text(step?.status) || "pending";
    return {
      errorCode: nullableText(step?.error_code),
      finishedAt: nullableText(step?.finished_at),
      id,
      label,
      startedAt: nullableText(step?.started_at),
      state: classifyStep(status, step),
      status,
    };
  });

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
