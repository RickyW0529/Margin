/**
 * @fileoverview API client for the Margin web frontend.
 *
 * Provides typed data models and thin fetch wrappers around the Margin REST API.
 * All helpers use a configurable base URL and default to `http://localhost:8000`.
 */

import { getAdminSession, setAdminSession } from "./admin-session";

/** Cursor pagination metadata returned by v0.2 dashboard list endpoints. */
export type DashboardPageInfo = {
  next_cursor: string | null;
  previous_cursor?: string | null;
  has_next_page: boolean;
  page_size: number;
};

/** Server-paginated v0.2 research candidate list item. */
export type ResearchCandidateListItemV2 = {
  item_id: string;
  security_id: string;
  symbol: string;
  name: string;
  scope_version_id: string;
  screening_status: string;
  data_status: string;
  risk_flags: string[];
  review_required: boolean;
  research_guardrail: string;
  current_review_outcome: string;
  effective_assessment_id: string | null;
  assessment_freshness: string;
  stale_reason: string | null;
  final_score: number | null;
  discount_rate: number | null;
  confidence: number | null;
  last_checked_at: string;
};

/** v0.2 research candidate list response with facets and page metadata. */
export type ResearchCandidateListResponse = {
  items: ResearchCandidateListItemV2[];
  page_info: DashboardPageInfo;
  facets: Record<string, Record<string, number>>;
  as_of: string;
  scope_version_id: string;
};

/** v0.2 research item detail aggregate for the company detail page. */
export type ResearchItemDetailV2 = {
  item: ResearchCandidateListItemV2;
  current_review: Record<string, unknown>;
  effective_assessment: Record<string, unknown>;
  factors: Record<string, unknown>;
  thesis: Record<string, unknown>;
  evidence: EvidenceLocatorListItem[];
  versions: Record<string, string>;
};

/** v0.2 research run progress detail. */
export type ResearchRunDetailV2 = {
  run_id: string;
  status: string;
  target_count: number;
  completed_count: number;
  pending_count: number;
  failed_count: number;
  wait_state: string | null;
  retry_after_seconds: number | null;
  supported_wait_states: string[];
  steps: Array<Record<string, unknown>>;
  trace_id: string | null;
};

/** Raw status returned by the valuation-discovery orchestrator. */
export type ValuationDiscoveryRunStatus = {
  run_id: string;
  state: string;
  scope_version_id: string;
  steps: Array<{
    step_id: string;
    state: string;
    attempt_no?: number;
    output_ref?: string | null;
    error_code?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
  }>;
};

/** Read-only dashboard Copilot response. */
export type ReadOnlyCopilotResponse = {
  answer: string;
  references: Array<Record<string, string>>;
};

/** Evidence locator row rendered in the v0.2 detail page. */
export type EvidenceLocatorListItem = {
  evidence_id: string;
  title?: string | null;
  source_level: string;
  locator: string;
  snapshot_id?: string | null;
  source_url?: string | null;
  pit_timestamp?: string | null;
};

/** Query filters accepted by the v0.2 research candidate list BFF. */
export type ResearchCandidateFilters = {
  scope_version_id: string;
  universe?: string;
  limit?: number;
  cursor?: string | null;
  screening_status?: string | null;
  data_status?: string | null;
  review_required?: string | boolean | null;
  assessment_freshness?: string | null;
  query?: string | null;
  sort_field?: string | null;
  sort_direction?: string | null;
};

/** A feedback record recorded against a research item. */
export type FeedbackRecord = {
  feedback_id: string;
  item_id: string;
  feedback_type: string;
  comment: string;
  created_at: string;
};

/** Allowed feedback decisions for a research item. */
export type FeedbackType = "accept" | "reject" | "watch" | "comment";

/** Status reported by a single data or model provider. */
export type ProviderStatus = {
  provider: string;
  status: string;
  message: string;
};

/** Write-only provider secret metadata returned by the v0.2 config API. */
export type ProviderSecretMetadata = {
  configured: boolean;
  last_four: string;
  version_id: string;
  status: string;
  updated_at: string;
  provider_name: string;
  secret_name: string;
};

/** Safe provider configuration summary rendered by Provider Settings. */
export type ProviderConfigSummary = {
  version_id: string;
  provider_name: string;
  provider_type: string;
  enabled: boolean;
  lifecycle: string;
  base_url?: string | null;
  model_name?: string | null;
  secret_metadata: ProviderSecretMetadata | null;
};

/** Result of testing one frozen provider config and secret version. */
export type ProviderHealthResult = {
  provider_name: string;
  provider_config_version_id: string;
  status: "ok" | "failed" | "not_configured";
  checked_at: string;
  latency_ms: number | null;
  error_code: string | null;
  redacted_error: string | null;
  secret_metadata: ProviderSecretMetadata | null;
};

/** Generic append-only strategy config version record. */
export type VersionedConfigRecord = Record<string, unknown> & {
  version_id?: string;
  lifecycle?: string;
  owner_id?: string;
};

/** Request body for starting a v0.2 valuation-discovery refresh. */
export type ValuationDiscoveryRefreshCreate = {
  scope_version_id: string;
  decision_at: string;
};

/** Response returned after a valuation-discovery refresh is accepted. */
export type ValuationDiscoveryRefreshStart = {
  run_id: string;
  status: string;
  http_status: number;
};

/** Request body for leaving feedback on a research item. */
export type ResearchFeedbackCreate = {
  feedback_type: FeedbackType;
  comment?: string;
};

const API_BASE_URL =
  process.env.MARGIN_API_BASE_URL ??
  process.env.NEXT_PUBLIC_MARGIN_API_BASE_URL ??
  "http://localhost:8000";

/** Fetch init variant that expects a plain JSON header record. */
type JsonRequestInit = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
};

/**
 * Performs a JSON request against the Margin API.
 *
 * GET requests are cached with a 30-second revalidation window; mutating
 * requests use `no-store`. Non-OK responses are converted into thrown errors
 * that include the status code and any response body detail.
 *
 * @param path - API path to request (appended to `API_BASE_URL`).
 * @param init - Optional fetch init options.
 * @returns A promise resolving to the parsed JSON response.
 * @throws Error when the response status is not OK.
 */
async function request<T>(path: string, init: JsonRequestInit = {}): Promise<T> {
  const method = init.method?.toUpperCase() ?? "GET";
  const cacheOptions =
    method === "GET" ? { next: { revalidate: 30 } } : { cache: "no-store" as const };
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...cacheOptions,
    ...init,
    headers: {
      accept: "application/json",
      ...init.headers,
    },
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    const suffix = detail ? ` - ${detail}` : "";
    throw new Error(`Margin API ${response.status}: ${path}${suffix}`);
  }

  return response.json() as Promise<T>;
}

/**
 * Performs a JSON POST request against the Margin API.
 *
 * @param path - API path to request.
 * @param body - Serializable request body.
 * @returns A promise resolving to the parsed JSON response.
 */
function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * Fetches the v0.2 server-paginated research candidate list.
 *
 * @param filters Scope, universe, pagination, and facet filters.
 * @returns A promise resolving to a paginated candidate response.
 */
export function fetchResearchCandidates(
  filters: ResearchCandidateFilters,
): Promise<ResearchCandidateListResponse> {
  const query = new URLSearchParams();
  appendQuery(query, "scope_version_id", filters.scope_version_id);
  appendQuery(query, "universe", filters.universe ?? "ALL_A");
  appendQuery(query, "limit", String(filters.limit ?? 50));
  appendQuery(query, "cursor", filters.cursor);
  appendQuery(query, "screening_status", filters.screening_status);
  appendQuery(query, "data_status", filters.data_status);
  appendQuery(query, "review_required", filters.review_required);
  appendQuery(query, "assessment_freshness", filters.assessment_freshness);
  appendQuery(query, "query", filters.query);
  appendQuery(query, "sort_field", filters.sort_field);
  appendQuery(query, "sort_direction", filters.sort_direction);

  return request<ResearchCandidateListResponse>(
    `/api/v1/research?${query.toString()}`,
  );
}

/**
 * Fetches the v0.2 research item detail aggregate.
 *
 * @param itemId - The unique research item identifier.
 * @returns A promise resolving to the current/effective detail payload.
 */
export function fetchResearchItemDetailV2(
  itemId: string,
): Promise<ResearchItemDetailV2> {
  return request<ResearchItemDetailV2>(`/api/v1/research/items/${itemId}`);
}

/**
 * Fetches the v0.2 research run progress detail.
 *
 * @param runId - The unique research run identifier.
 * @returns A promise resolving to a run progress payload.
 */
export function fetchResearchRunDetailV2(
  runId: string,
): Promise<ResearchRunDetailV2> {
  return request<ValuationDiscoveryRunStatus>(
    `/api/v1/valuation-discovery/runs/${runId}`,
  ).then(mapValuationDiscoveryRunStatus);
}

/** Calls the read-only dashboard Copilot endpoint. */
export function askReadOnlyCopilot(requestBody: {
  scope_version_id: string;
  message: string;
  universe?: string;
}): Promise<ReadOnlyCopilotResponse> {
  return post<ReadOnlyCopilotResponse>(
    "/api/v1/research/copilot",
    requestBody,
  );
}

/**
 * Fetches the health/status of external data and model providers.
 *
 * @returns A promise resolving to the provider status list.
 */
export function fetchProviderStatus(): Promise<ProviderStatus[]> {
  return request<ProviderStatus[]>("/api/v1/provider-status");
}

/** Fetches safe provider config metadata without secret contents. */
export function fetchProviderConfigs(): Promise<ProviderConfigSummary[]> {
  return request<ProviderConfigSummary[]>("/api/v1/provider-configs");
}

/** Fetches universe definition versions for settings pages. */
export function fetchUniverseConfigs(): Promise<VersionedConfigRecord[]> {
  return request<VersionedConfigRecord[]>("/api/v1/universe-configs");
}

/** Fetches indicator view versions for settings pages. */
export function fetchIndicatorViews(): Promise<VersionedConfigRecord[]> {
  return request<VersionedConfigRecord[]>("/api/v1/indicator-views");
}

/** Fetches frozen research scope versions for settings pages. */
export function fetchResearchScopes(): Promise<VersionedConfigRecord[]> {
  return request<VersionedConfigRecord[]>("/api/v1/research-scopes");
}

/** Fetches quant feature set versions for settings pages. */
export function fetchQuantFeatureSets(): Promise<VersionedConfigRecord[]> {
  return request<VersionedConfigRecord[]>("/api/v1/quant-feature-sets");
}

/** Fetches quant strategy versions for settings pages. */
export function fetchQuantStrategies(): Promise<VersionedConfigRecord[]> {
  return request<VersionedConfigRecord[]>("/api/v1/quant-strategies");
}

/** Fetches style prompt versions for settings pages. */
export function fetchStylePrompts(): Promise<VersionedConfigRecord[]> {
  return request<VersionedConfigRecord[]>("/api/v1/style-prompts");
}

/**
 * Writes a provider secret using a browser-session admin credential.
 *
 * The admin token and CSRF token are read from sessionStorage so they are not
 * compiled into the browser bundle or persisted across browser restarts.
 */
export function saveProviderSecret(
  providerConfigId: string,
  secretName: string,
  secretValue: string,
): Promise<ProviderSecretMetadata> {
  const adminToken = readSessionCredential("margin.adminApiToken");
  const csrfToken = readSessionCredential("margin.csrfToken");
  if (!adminToken || !csrfToken) {
    return Promise.reject(
      new Error("Local admin session is not configured in this browser tab"),
    );
  }
  return request<ProviderSecretMetadata>(
    `/api/v1/provider-configs/${providerConfigId}/secret`,
    {
      method: "PUT",
      cache: "no-store",
      headers: {
        "content-type": "application/json",
        Authorization: `Bearer ${adminToken}`,
        "Idempotency-Key": globalThis.crypto.randomUUID(),
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({
        secret_name: secretName,
        secret_value: secretValue,
      }),
    },
  );
}

/** Runs a read-only real provider health check. */
export function testProviderConfig(
  providerConfigId: string,
): Promise<ProviderHealthResult> {
  const adminToken = readSessionCredential("margin.adminApiToken");
  const csrfToken = readSessionCredential("margin.csrfToken");
  if (!adminToken || !csrfToken) {
    return Promise.reject(
      new Error("Local admin session is not configured in this browser tab"),
    );
  }
  return request<ProviderHealthResult>(
    `/api/v1/provider-configs/${providerConfigId}/test`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${adminToken}`,
        "Idempotency-Key": globalThis.crypto.randomUUID(),
        "X-CSRF-Token": csrfToken,
      },
    },
  );
}

/** Starts the v0.2 valuation-discovery pipeline using local admin credentials. */
export function startValuationDiscoveryRefresh(
  refresh: ValuationDiscoveryRefreshCreate,
): Promise<ValuationDiscoveryRefreshStart> {
  const adminToken = readSessionCredential("margin.adminApiToken");
  const csrfToken = readSessionCredential("margin.csrfToken");
  if (!adminToken || !csrfToken) {
    return Promise.reject(
      new Error("Local admin session is not configured in this browser tab"),
    );
  }
  return request<ValuationDiscoveryRefreshStart>(
    "/api/v1/valuation-discovery/refreshes",
    {
      method: "POST",
      cache: "no-store",
      headers: {
        "content-type": "application/json",
        Authorization: `Bearer ${adminToken}`,
        "Idempotency-Key": globalThis.crypto.randomUUID(),
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(refresh),
    },
  );
}

/** Stores local admin credentials for the current browser tab only. */
export function configureLocalAdminSession(
  adminToken: string,
  csrfToken: string,
): void {
  setAdminSession(adminToken, csrfToken, true);
}

function readSessionCredential(key: string): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const session = getAdminSession();
  if (session === null) {
    return null;
  }
  if (key === "margin.adminApiToken") {
    return session.adminToken;
  }
  if (key === "margin.csrfToken") {
    return session.csrfToken;
  }
  return null;
}

function appendQuery(
  query: URLSearchParams,
  key: string,
  value: boolean | number | string | null | undefined,
): void {
  if (value === null || value === undefined || value === "") {
    return;
  }
  query.set(key, String(value));
}

function mapValuationDiscoveryRunStatus(
  run: ValuationDiscoveryRunStatus,
): ResearchRunDetailV2 {
  const targetCount = run.steps.length;
  const completedCount = run.steps.filter((step) =>
    ["skipped", "succeeded", "succeeded_with_degradation"].includes(step.state),
  ).length;
  const failedCount = run.steps.filter((step) =>
    ["cancelled", "failed_final"].includes(step.state),
  ).length;
  const waitingStep = run.steps.find((step) => step.state.startsWith("waiting"));
  const retryableFailure = run.steps.find(
    (step) => step.state === "failed_retryable",
  );
  return {
    completed_count: completedCount,
    failed_count: failedCount,
    pending_count: Math.max(targetCount - completedCount - failedCount, 0),
    retry_after_seconds: null,
    run_id: run.run_id,
    status: run.state,
    steps: run.steps.map((step) => ({
      attempt_no: step.attempt_no ?? null,
      error_code: step.error_code ?? null,
      finished_at: step.finished_at ?? null,
      output_ref: step.output_ref ?? null,
      started_at: step.started_at ?? null,
      status: step.state,
      step: step.step_id,
    })),
    supported_wait_states: [
      "waiting_provider",
      "waiting_rate_limit",
      "waiting_retry",
    ],
    target_count: targetCount,
    trace_id: run.run_id,
    wait_state: waitingStep
      ? mapWaitState(waitingStep.state)
      : retryableFailure
        ? "waiting_retry"
        : null,
  };
}

function mapWaitState(state: string): string {
  if (state === "waiting_rate_limit") {
    return "waiting_rate_limit";
  }
  if (state === "waiting_budget") {
    return "waiting_provider";
  }
  return state;
}

/**
 * Leaves feedback on a research item.
 *
 * @param itemId - The unique research item identifier.
 * @param request - Feedback creation parameters.
 * @returns A promise resolving to the created feedback record.
 */
export function createResearchItemFeedback(
  itemId: string,
  request: ResearchFeedbackCreate,
): Promise<FeedbackRecord> {
  return post<FeedbackRecord>(
    `/api/v1/research-items/${itemId}/feedback`,
    request,
  );
}

/** One refresh run row in the v0.2 valuation-discovery list view. */
export type ValuationDiscoveryRefreshSummary = {
  run_id: string;
  state: string;
  scope_version_id: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

/** Cursor-paginated refresh run list response. */
export type ValuationDiscoveryRefreshListResponse = {
  items: ValuationDiscoveryRefreshSummary[];
  next_cursor: string | null;
  page_size: number;
};

/** Query filters accepted by the v0.2 valuation-discovery run list endpoint. */
export type ValuationDiscoveryRunListFilters = {
  scope_version_id?: string | null;
  state?: string | null;
  limit?: number;
  cursor?: string | null;
};

/** Loads recent valuation-discovery refresh runs, newest first. */
export function fetchValuationDiscoveryRuns(
  filters: ValuationDiscoveryRunListFilters = {},
): Promise<ValuationDiscoveryRefreshListResponse> {
  const query = new URLSearchParams();
  appendQuery(query, "scope_version_id", filters.scope_version_id);
  appendQuery(query, "state", filters.state);
  appendQuery(query, "limit", String(filters.limit ?? 50));
  return request<ValuationDiscoveryRefreshListResponse>(
    `/api/v1/valuation-discovery/runs?${query.toString()}`,
  );
}

/** Built-in strategy template metadata returned by GET /strategies/templates. */
export type StrategyTemplate = {
  template_id: string;
  name: string;
  description: string;
  category: string;
};

/** Arbitrary JSON shape returned by the strategy endpoints. */
export type StrategyProfile = Record<string, unknown> & {
  strategy_id?: string;
  owner_id?: string;
  name?: string;
  description?: string;
  versions?: Array<Record<string, unknown>>;
};

/** Request body for creating a strategy from a built-in template. */
export type CreateStrategyRequest = {
  owner_id: string;
  template: string;
  name?: string;
  description?: string;
};

/** Request body for creating a fully custom strategy. */
export type CreateCustomStrategyRequest = {
  owner_id: string;
  config: Record<string, unknown>;
  name: string;
  description?: string;
};

/** Request body for creating a new version of an existing strategy. */
export type UpdateStrategyRequest = {
  config_delta?: Record<string, unknown>;
  name?: string;
  description?: string;
};

/** Merged prompt response returned by GET /strategies/{id}/versions/{v}/prompt. */
export type StrategyPromptResponse = {
  prompt: string;
};

/** Lists available built-in strategy templates. */
export function fetchStrategyTemplates(): Promise<StrategyTemplate[]> {
  return request<StrategyTemplate[]>(`/strategies/templates`);
}

/** Lists strategy profiles owned by the given owner. */
export function fetchStrategies(ownerId: string): Promise<StrategyProfile[]> {
  const query = new URLSearchParams({ owner_id: ownerId });
  return request<StrategyProfile[]>(`/strategies?${query.toString()}`);
}

/** Returns a single strategy profile by id. */
export function fetchStrategyDetail(strategyId: string): Promise<StrategyProfile> {
  return request<StrategyProfile>(`/strategies/${strategyId}`);
}

/** Creates a strategy from a built-in template. */
export function createStrategy(
  body: CreateStrategyRequest,
): Promise<StrategyProfile> {
  return post<StrategyProfile>(`/strategies`, body);
}

/** Creates a strategy from a fully custom configuration. */
export function createCustomStrategy(
  body: CreateCustomStrategyRequest,
): Promise<StrategyProfile> {
  return post<StrategyProfile>(`/strategies/custom`, body);
}

/** Creates a new version of an existing strategy. */
export function updateStrategy(
  strategyId: string,
  body: UpdateStrategyRequest,
): Promise<StrategyProfile> {
  return request<StrategyProfile>(`/strategies/${strategyId}`, {
    method: "PUT",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Validates a strategy version, advancing it to the backtesting stage. */
export function validateStrategyVersion(
  strategyId: string,
  versionId: string,
): Promise<StrategyProfile> {
  return post<StrategyProfile>(
    `/strategies/${strategyId}/versions/${versionId}/validate`,
    {},
  );
}

/** Advances a strategy version from backtesting to paper trading. */
export function backtestStrategyVersion(
  strategyId: string,
  versionId: string,
): Promise<StrategyProfile> {
  return post<StrategyProfile>(
    `/strategies/${strategyId}/versions/${versionId}/backtest`,
    {},
  );
}

/** Advances a strategy version from paper trading to active-ready. */
export function paperTradeStrategyVersion(
  strategyId: string,
  versionId: string,
): Promise<StrategyProfile> {
  return post<StrategyProfile>(
    `/strategies/${strategyId}/versions/${versionId}/paper-trade`,
    {},
  );
}

/** Activates a strategy version for live research runs. */
export function activateStrategyVersion(
  strategyId: string,
  versionId: string,
): Promise<StrategyProfile> {
  return post<StrategyProfile>(
    `/strategies/${strategyId}/versions/${versionId}/activate`,
    {},
  );
}

/** Archives the active version of a strategy. */
export function archiveStrategy(strategyId: string): Promise<StrategyProfile> {
  return post<StrategyProfile>(`/strategies/${strategyId}/archive`, {});
}

/** Returns the merged prompt for a strategy version and optional task name. */
export function fetchStrategyPrompt(
  strategyId: string,
  versionId: string,
  task = "",
): Promise<StrategyPromptResponse> {
  const query = new URLSearchParams();
  appendQuery(query, "task", task);
  const qs = query.toString();
  return request<StrategyPromptResponse>(
    `/strategies/${strategyId}/versions/${versionId}/prompt${qs ? `?${qs}` : ""}`,
  );
}
