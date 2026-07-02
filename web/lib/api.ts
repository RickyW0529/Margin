/**
 * @fileoverview API client for the Margin web frontend.
 *
 * Provides typed data models and thin fetch wrappers around the Margin REST API.
 * All helpers use a configurable base URL and default to `http://localhost:8000`.
 */

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
  factors: ResearchDetailFactors;
  thesis: ResearchDetailThesis;
  evidence: EvidenceLocatorListItem[];
  versions: Record<string, string>;
};

/** Research detail thesis text and AI status. */
export type ResearchDetailThesis = Record<string, unknown> & {
  statement?: string | null;
  ai_status?: string | null;
};

/** One metric trend series rendered on the recommendation detail page. */
export type MetricTrend = {
  metric: string;
  label: string;
  unit?: string | null;
  points: Array<{ date: string; value: number | null }>;
};

/** One compact raw metric tile on the recommendation detail page. */
export type RawMetricCard = {
  metric: string;
  label: string;
  value: number | null;
  unit?: string | null;
};

/** Valuation state rendered on the recommendation detail page. */
export type ValuationState = {
  discount_rate?: number | null;
  intrinsic_value?: number | null;
  margin_of_safety?: number | null;
  status?: string | null;
  message?: string | null;
};

/** Factors plus visualization extras used by the recommendation detail page. */
export type ResearchDetailFactors = Record<string, unknown> & {
  valuation?: ValuationState;
  trends?: MetricTrend[];
  raw_metrics?: RawMetricCard[];
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
  source_name?: string | null;
  snippet?: string | null;
  linked_to_security?: boolean | null;
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
  provider_category?: string;
  detected_provider?: string;
  detected_label?: string;
  is_custom_provider?: boolean;
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

/** Immutable rolling-window data acquisition policy. */
export type DataPolicyVersion = {
  version_id: string;
  owner_id: string;
  rolling_window_months: number;
  revision_lookback_days: number;
  financial_comparison_years: number;
  lifecycle: string;
  config_hash: string;
  created_at: string;
  activated_at: string | null;
  window_start: string;
  window_end: string;
};

/** Data policy list response used by the settings page. */
export type DataPolicyListResponse = {
  active_version_id: string;
  versions: DataPolicyVersion[];
};

/** Request for creating a new rolling-window policy version. */
export type DataPolicyCreate = {
  rolling_window_months: number;
  revision_lookback_days: number;
  financial_comparison_years: number;
};

/** Generic append-only strategy config version record. */
export type VersionedConfigRecord = Record<string, unknown> & {
  version_id?: string;
  lifecycle?: string;
  owner_id?: string;
};

/** One monthly manual quant preset exposed by the backend. */
export type QuantStrategyPreset = {
  universe_code: string;
  label: string;
  benchmark_index_code: string | null;
  rebalance_frequency: string;
  buy_threshold: number;
  sell_threshold: number;
  min_avg_amount_20d: number;
  weighting: string;
  factor_weights: Record<string, number>;
  candidate_policy: Record<string, unknown>;
  calibration: Record<string, unknown>;
};

/** Built-in quant defaults for the user-facing strategy customizer. */
export type QuantStrategyDefaults = {
  profile: string;
  default_universe: string;
  execution_boundary: string;
  presets: Record<string, QuantStrategyPreset>;
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
  next?: { revalidate?: number | false };
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
  const hasExplicitCache = init.cache !== undefined || init.next !== undefined;
  const cacheOptions = hasExplicitCache
    ? {}
    : method === "GET"
      ? { next: { revalidate: 30 } }
      : { cache: "no-store" as const };
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
    { cache: "no-store" },
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
  return request<ProviderStatus[]>("/api/v1/provider-status", {
    cache: "no-store",
  });
}

/** Fetches safe provider config metadata without secret contents. */
export function fetchProviderConfigs(): Promise<ProviderConfigSummary[]> {
  return request<ProviderConfigSummary[]>("/api/v1/provider-configs", {
    cache: "no-store",
  });
}

/** Fetches all rolling-window policy versions and the active version ID. */
export function fetchDataPolicies(): Promise<DataPolicyListResponse> {
  return request<DataPolicyListResponse>("/api/v1/data-policies");
}

/** Creates an append-only rolling-window policy version. */
export function createDataPolicy(
  policy: DataPolicyCreate,
): Promise<DataPolicyVersion> {
  return authenticatedMutation<DataPolicyVersion>(
    "/api/v1/data-policies",
    "POST",
    policy,
  );
}

/** Activates one rolling-window policy version. */
export function activateDataPolicy(
  versionId: string,
): Promise<DataPolicyVersion> {
  return authenticatedMutation<DataPolicyVersion>(
    `/api/v1/data-policies/${versionId}/activate`,
    "POST",
  );
}

/** Creates an asynchronous data-sync run using the active data policy. */
export function triggerDataSync(
  body: Record<string, unknown> = {},
): Promise<{ sync_run_id: string; status: string }> {
  return authenticatedMutation<{ sync_run_id: string; status: string }>(
    "/api/v1/data-sync",
    "POST",
    body,
  );
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

/** Fetches built-in quant strategy presets for supported company pools. */
export function fetchQuantStrategyDefaults(): Promise<QuantStrategyDefaults> {
  return request<QuantStrategyDefaults>("/api/v1/quant-strategy-defaults");
}

/** Fetches style prompt versions for settings pages. */
export function fetchStylePrompts(): Promise<VersionedConfigRecord[]> {
  return request<VersionedConfigRecord[]>("/api/v1/style-prompts");
}

/** Writes a provider secret in local personal mode. */
export function saveProviderSecret(
  providerConfigId: string,
  secretName: string,
  secretValue: string,
): Promise<ProviderSecretMetadata> {
  return request<ProviderSecretMetadata>(
    `/api/v1/provider-configs/${providerConfigId}/secret`,
    {
      method: "PUT",
      cache: "no-store",
      headers: {
        "content-type": "application/json",
        "Idempotency-Key": globalThis.crypto.randomUUID(),
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
  return request<ProviderHealthResult>(
    `/api/v1/provider-configs/${providerConfigId}/test`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        "Idempotency-Key": globalThis.crypto.randomUUID(),
      },
    },
  );
}

function authenticatedMutation<T>(
  path: string,
  method: "POST" | "PUT",
  body?: unknown,
): Promise<T> {
  return request<T>(path, {
    method,
    cache: "no-store",
    headers: {
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      "Idempotency-Key": globalThis.crypto.randomUUID(),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** Starts the v0.2 valuation-discovery pipeline in local personal mode. */
export function startValuationDiscoveryRefresh(
  refresh: ValuationDiscoveryRefreshCreate,
): Promise<ValuationDiscoveryRefreshStart> {
  return request<ValuationDiscoveryRefreshStart>(
    "/api/v1/valuation-discovery/refreshes",
    {
      method: "POST",
      cache: "no-store",
      headers: {
        "content-type": "application/json",
        "Idempotency-Key": globalThis.crypto.randomUUID(),
      },
      body: JSON.stringify(refresh),
    },
  );
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
    { cache: "no-store" },
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

/** Versioned strategy-config resource kinds backed by append-only endpoints. */
export type VersionedConfigKind =
  | "universe-configs"
  | "indicator-views"
  | "quant-feature-sets"
  | "quant-strategies"
  | "style-prompts"
  | "research-scopes";

/** Creates an append-only versioned config of the given kind. */
export function createVersionedConfig(
  kind: VersionedConfigKind,
  body: Record<string, unknown>,
): Promise<VersionedConfigRecord> {
  return authenticatedMutation<VersionedConfigRecord>(
    `/api/v1/${kind}`,
    "POST",
    body,
  );
}

/** Activates one versioned config version of the given kind. */
export function activateVersionedConfig(
  kind: VersionedConfigKind,
  versionId: string,
): Promise<VersionedConfigRecord> {
  return authenticatedMutation<VersionedConfigRecord>(
    `/api/v1/${kind}/${versionId}/activate`,
    "POST",
  );
}

/** Creates an append-only provider configuration version. */
export function createProviderConfig(
  body: Record<string, unknown>,
): Promise<VersionedConfigRecord> {
  return authenticatedMutation<VersionedConfigRecord>(
    "/api/v1/provider-configs",
    "POST",
    body,
  );
}

/** Activates a provider config version after a successful health check. */
export function activateProviderConfig(
  versionId: string,
): Promise<VersionedConfigRecord> {
  return authenticatedMutation<VersionedConfigRecord>(
    `/api/v1/provider-configs/${versionId}/activate`,
    "POST",
  );
}

/** News WebSearch run status returned by GET /api/v1/news/runs/{run_id}. */
export type NewsRunStatus = Record<string, unknown> & {
  run_id?: string;
  state?: string;
};

/** Fetches a news WebSearch run status. */
export function fetchNewsRun(runId: string): Promise<NewsRunStatus> {
  return request<NewsRunStatus>(`/api/v1/news/runs/${runId}`);
}

/** Dashboard job run record returned by GET /api/v1/jobs/{job_run_id}. */
export type JobRun = Record<string, unknown> & {
  job_run_id?: string;
  state?: string;
};

/** Fetches a dashboard job run record. */
export function fetchJobRun(jobRunId: string): Promise<JobRun> {
  return request<JobRun>(`/api/v1/jobs/${jobRunId}`);
}

// ---------------------------------------------------------------------------
// Company quant / analysis profile (visualization-facing)
// ---------------------------------------------------------------------------

/** Single factor group score with label and weight. */
export type FactorScoreItem = {
  factor_key: string;
  label: string;
  score: number | null;
  weight: number;
};

/** Quant screening profile for one security. */
export type CompanyQuantProfile = {
  security_id: string;
  quant_run_id: string;
  result_id: string;
  decision_at: string;
  final_score: number;
  factor_scores: FactorScoreItem[];
  rank_overall: number | null;
  rank_in_industry: number | null;
  screening_status: string;
  data_status: string;
  risk_flags: string[];
  review_required: boolean;
  review_reasons: string[];
  research_guardrail: string;
  reason_summary: string;
  factor_details: Record<string, unknown>;
};

/** One Analysis Mart metric row. */
export type AnalysisMetric = {
  metric_id: string;
  metric_code: string;
  metric_name: string;
  metric_group: string;
  numeric_value: number | null;
  unit: string | null;
  direction: string;
  percentile_market: number | null;
  percentile_industry: number | null;
  rank_market: number | null;
  rank_industry: number | null;
};

/** One Analysis Mart finding row. */
export type AnalysisFinding = {
  finding_id: string;
  finding_type: string;
  severity: string;
  title: string;
  description: string;
  confidence: number;
  evidence_ids: string[];
};

/** Header metadata for an analysis snapshot. */
export type AnalysisSnapshotHeader = {
  analysis_snapshot_id: string;
  decision_at: string;
  trading_date: string;
  analysis_version: string;
  analysis_kind: string;
  quant_run_id: string | null;
  quant_result_id: string | null;
  input_hash: string;
  result_hash: string;
};

/** Fourth-layer Analysis Mart profile for one security. */
export type CompanyAnalysisProfile = {
  security_id: string;
  snapshot: AnalysisSnapshotHeader | null;
  metrics: AnalysisMetric[];
  findings: AnalysisFinding[];
  evidence_link_count: number;
};

/** Fetches the latest quant screening profile for a security. */
export function fetchCompanyQuantProfile(
  securityId: string,
): Promise<CompanyQuantProfile> {
  return request<CompanyQuantProfile>(
    `/api/v1/valuation-discovery/companies/${securityId}/quant`,
  );
}

/** Fetches the Analysis Mart profile for a security.
 *
 * When `scopeVersionId` is omitted, the latest snapshot across all scopes is
 * returned.
 */
export function fetchCompanyAnalysisProfile(
  securityId: string,
  scopeVersionId?: string,
): Promise<CompanyAnalysisProfile> {
  const path = `/api/v1/valuation-discovery/companies/${securityId}/analysis`;
  if (scopeVersionId) {
    const params = new URLSearchParams({ scope_version_id: scopeVersionId });
    return request<CompanyAnalysisProfile>(`${path}?${params}`);
  }
  return request<CompanyAnalysisProfile>(path);
}
