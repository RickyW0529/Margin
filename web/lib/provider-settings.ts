import type { ProviderConfigSummary } from "@/lib/api";

export type ProviderCategoryId =
  | "llm"
  | "web_search"
  | "data_source"
  | "embedding"
  | "rerank";

export type ProviderCategoryDefinition = {
  id: ProviderCategoryId;
  title: string;
  providerType: string;
  defaultProviderName: string;
  urlLabel: string;
  tokenPlaceholder: string;
  modelLabel?: string;
};

export type ProviderDetection = {
  providerId: string;
  label: string;
  isCustom: boolean;
};

export type ProviderPreset = {
  providerId: string;
  label: string;
  baseUrl: string;
  model?: string;
  isCustom?: boolean;
};

const CUSTOM_PROVIDER_PRESET: ProviderPreset = {
  providerId: "custom",
  label: "自定义",
  baseUrl: "",
  isCustom: true,
};

export const PROVIDER_CATEGORIES: ProviderCategoryDefinition[] = [
  {
    id: "llm",
    title: "LLM 配置",
    providerType: "llm",
    defaultProviderName: "llm",
    urlLabel: "LLM URL",
    tokenPlaceholder: "sk-...",
    modelLabel: "模型名",
  },
  {
    id: "web_search",
    title: "网页搜索配置",
    providerType: "websearch",
    defaultProviderName: "web_search",
    urlLabel: "搜索 API URL",
    tokenPlaceholder: "tvly-...",
  },
  {
    id: "data_source",
    title: "数据源配置",
    providerType: "market_data",
    defaultProviderName: "data_source",
    urlLabel: "数据源 URL",
    tokenPlaceholder: "token",
  },
  {
    id: "embedding",
    title: "向量化模型配置",
    providerType: "embedding",
    defaultProviderName: "embedding",
    urlLabel: "Embedding URL",
    tokenPlaceholder: "sk-...",
    modelLabel: "模型名",
  },
  {
    id: "rerank",
    title: "Rerank 配置",
    providerType: "rerank",
    defaultProviderName: "rerank",
    urlLabel: "Rerank URL",
    tokenPlaceholder: "token",
    modelLabel: "模型名",
  },
];

export const PROVIDER_PRESETS: Record<ProviderCategoryId, ProviderPreset[]> = {
  llm: [
    {
      providerId: "deepseek",
      label: "DeepSeek",
      baseUrl: "https://api.deepseek.com/v1",
      model: "deepseek-chat",
    },
    {
      providerId: "minimax",
      label: "Minimax",
      baseUrl: "https://api.minimaxi.com/v1",
      model: "MiniMax-M3",
    },
    {
      providerId: "openai",
      label: "OpenAI",
      baseUrl: "https://api.openai.com/v1",
      model: "gpt-4o-mini",
    },
    {
      providerId: "zhipu",
      label: "Zhipu",
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "glm-4-flash",
    },
    {
      providerId: "qwen",
      label: "Qwen",
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      model: "qwen-plus",
    },
    CUSTOM_PROVIDER_PRESET,
  ],
  web_search: [
    {
      providerId: "tavily",
      label: "Tavily",
      baseUrl: "https://api.tavily.com/search",
    },
    {
      providerId: "firecrawl",
      label: "Firecrawl",
      baseUrl: "https://api.firecrawl.dev",
    },
    CUSTOM_PROVIDER_PRESET,
  ],
  data_source: [
    {
      providerId: "tushare",
      label: "Tushare",
      baseUrl: "https://api.tushare.pro",
    },
    CUSTOM_PROVIDER_PRESET,
  ],
  embedding: [
    {
      providerId: "zhipu",
      label: "Zhipu",
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      model: "embedding-3",
    },
    {
      providerId: "openai_compatible",
      label: "OpenAI Compatible",
      baseUrl: "https://api.openai.com/v1",
      model: "text-embedding-3-small",
    },
    CUSTOM_PROVIDER_PRESET,
  ],
  rerank: [
    {
      providerId: "jina",
      label: "Jina",
      baseUrl: "https://api.jina.ai/v1/rerank",
      model: "jina-reranker-v2-base-multilingual",
    },
    CUSTOM_PROVIDER_PRESET,
  ],
};

type ProviderRule = {
  providerId: string;
  label: string;
  pattern: RegExp;
};

const RULES: Record<ProviderCategoryId, ProviderRule[]> = {
  llm: [
    { providerId: "deepseek", label: "DeepSeek", pattern: /deepseek\.com/i },
    { providerId: "minimax", label: "Minimax", pattern: /platform\.minimaxi\.com|minimaxi\.com/i },
    { providerId: "modelscope", label: "ModelScope", pattern: /api-inference\.modelscope\.cn|modelscope\.cn/i },
    { providerId: "zhipu", label: "Zhipu", pattern: /open\.bigmodel\.cn|bigmodel\.cn/i },
    { providerId: "ollama", label: "Ollama", pattern: /(localhost|127\.0\.0\.1|\[::1\]):11434/i },
    { providerId: "vllm", label: "VLLM", pattern: /(localhost|127\.0\.0\.1|\[::1\]):8000/i },
    { providerId: "local", label: "Local", pattern: /localhost|127\.0\.0\.1|\[::1\]/i },
    { providerId: "openai", label: "OpenAI", pattern: /api\.openai\.com|openai\.com/i },
    { providerId: "openrouter", label: "OpenRouter", pattern: /openrouter\.ai/i },
    { providerId: "qwen", label: "Qwen", pattern: /dashscope|aliyuncs\.com/i },
    { providerId: "gemini", label: "Gemini", pattern: /generativelanguage\.googleapis\.com/i },
    { providerId: "anthropic", label: "Anthropic", pattern: /anthropic\.com/i },
  ],
  web_search: [
    { providerId: "tavily", label: "Tavily", pattern: /tavily\.com/i },
    {
      providerId: "firecrawl",
      label: "Firecrawl",
      pattern: /firecrawl\.dev|firecrawl\.com/i,
    },
    { providerId: "exa", label: "Exa", pattern: /exa\.ai/i },
    { providerId: "serpapi", label: "SerpAPI", pattern: /serpapi\.com/i },
    { providerId: "bing", label: "Bing", pattern: /bing\.microsoft\.com|api\.bing\.microsoft/i },
  ],
  data_source: [
    { providerId: "tushare", label: "Tushare", pattern: /tushare|teajoin\.com/i },
    { providerId: "akshare", label: "AKShare", pattern: /akshare/i },
  ],
  embedding: [
    { providerId: "zhipu", label: "Zhipu", pattern: /open\.bigmodel\.cn|bigmodel\.cn/i },
    { providerId: "openai_compatible", label: "OpenAI Compatible", pattern: /openai\.com|\/embeddings?/i },
    { providerId: "dashscope", label: "DashScope", pattern: /dashscope|aliyuncs\.com/i },
    { providerId: "jina", label: "Jina", pattern: /jina\.ai/i },
  ],
  rerank: [
    { providerId: "jina", label: "Jina", pattern: /jina\.ai/i },
    { providerId: "cohere", label: "Cohere", pattern: /cohere\.ai/i },
  ],
};

const CATEGORY_ALIASES: Record<string, ProviderCategoryId> = {
  ai: "llm",
  llm: "llm",
  websearch: "web_search",
  web_search: "web_search",
  market_data: "data_source",
  data_source: "data_source",
  data: "data_source",
  embedding: "embedding",
  rerank: "rerank",
};

const PROVIDER_CATEGORY_BY_NAME: Record<string, ProviderCategoryId> = {
  llm: "llm",
  deepseek: "llm",
  minimax: "llm",
  modelscope: "llm",
  zhipu: "llm",
  openai: "llm",
  ollama: "llm",
  vllm: "llm",
  local: "llm",
  tavily: "web_search",
  exa: "web_search",
  tushare: "data_source",
  akshare: "data_source",
  embedding: "embedding",
  rerank: "rerank",
  jina: "embedding",
};

export function categoryForProvider(
  provider: ProviderConfigSummary,
): ProviderCategoryId {
  const explicit = provider.provider_category?.toLowerCase();
  if (explicit && explicit in CATEGORY_ALIASES) {
    return CATEGORY_ALIASES[explicit];
  }
  const byType = provider.provider_type.toLowerCase();
  if (byType in CATEGORY_ALIASES) {
    return CATEGORY_ALIASES[byType];
  }
  const byName = provider.provider_name.toLowerCase();
  return PROVIDER_CATEGORY_BY_NAME[byName] ?? "data_source";
}

export function detectProviderLabel(
  category: ProviderCategoryId,
  url: string | null | undefined,
): ProviderDetection {
  const normalized = url?.trim() ?? "";
  for (const rule of RULES[category]) {
    if (normalized && rule.pattern.test(normalized)) {
      return {
        providerId: rule.providerId,
        label: rule.label,
        isCustom: false,
      };
    }
  }
  return { providerId: "custom", label: "Custom", isCustom: true };
}

export function displayDetection(
  category: ProviderCategoryId,
  provider: ProviderConfigSummary | null,
  draftUrl: string,
): ProviderDetection {
  if (provider?.detected_label && provider.detected_provider) {
    return {
      providerId: provider.detected_provider,
      label: provider.detected_label,
      isCustom: provider.is_custom_provider ?? false,
    };
  }
  return detectProviderLabel(category, provider?.base_url ?? draftUrl);
}

export function providerPresetOptions(
  category: ProviderCategoryId,
): ProviderPreset[] {
  return PROVIDER_PRESETS[category];
}

export function providerPresetForId(
  category: ProviderCategoryId,
  providerId: string,
): ProviderPreset | null {
  return (
    PROVIDER_PRESETS[category].find(
      (preset) => preset.providerId === providerId,
    ) ?? null
  );
}

export function providerPresetForProvider(
  category: ProviderCategoryId,
  provider: ProviderConfigSummary | null,
): ProviderPreset {
  if (provider?.detected_provider) {
    const byDetectedProvider = providerPresetForId(
      category,
      provider.detected_provider,
    );
    if (byDetectedProvider) {
      return byDetectedProvider;
    }
  }
  const detection = detectProviderLabel(category, provider?.base_url);
  if (!detection.isCustom) {
    const byUrl = providerPresetForId(category, detection.providerId);
    if (byUrl) {
      return byUrl;
    }
  }
  return CUSTOM_PROVIDER_PRESET;
}

export function chooseProviderForCategory(
  providers: ProviderConfigSummary[],
  category: ProviderCategoryId,
): ProviderConfigSummary | null {
  const matches = providers.filter(
    (provider) => categoryForProvider(provider) === category,
  );
  const configured = matches
    .filter((provider) => provider.secret_metadata?.configured)
    .sort(
      (left, right) =>
        secretUpdatedAt(right) - secretUpdatedAt(left),
    );
  return (
    configured[0] ??
    matches.find((provider) => provider.lifecycle === "active") ??
    matches[0] ??
    null
  );
}

function secretUpdatedAt(provider: ProviderConfigSummary): number {
  const updatedAt = provider.secret_metadata?.updated_at;
  if (!updatedAt) {
    return 0;
  }
  const timestamp = Date.parse(updatedAt);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export function providerNameForCategory(
  category: ProviderCategoryDefinition,
  detection: ProviderDetection,
): string {
  if (category.id === "web_search" && detection.providerId !== "custom") {
    return detection.providerId;
  }
  if (category.id === "data_source" && detection.providerId !== "custom") {
    return detection.providerId;
  }
  return category.defaultProviderName;
}

export function defaultSecretName(
  category: ProviderCategoryId,
  providerName: string,
): string {
  if (category === "data_source" && providerName.toLowerCase().includes("tushare")) {
    return "api_token";
  }
  return "api_key";
}
