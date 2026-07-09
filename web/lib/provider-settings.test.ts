import { describe, expect, it } from "vitest";

import {
  chooseProviderForCategory,
  detectProviderLabel,
  providerNameForCategory,
} from "./provider-settings";

describe("provider settings detection", () => {
  it("detects ModelScope and local OpenAI-compatible LLM URLs", () => {
    expect(
      detectProviderLabel("llm", "https://api-inference.modelscope.cn/v1/"),
    ).toMatchObject({ providerId: "modelscope", label: "ModelScope" });
    expect(
      detectProviderLabel("llm", "https://platform.minimaxi.com"),
    ).toMatchObject({ providerId: "minimax", label: "Minimax" });
    expect(
      detectProviderLabel("llm", "https://api.minimaxi.com/v1"),
    ).toMatchObject({ providerId: "minimax", label: "Minimax" });
    expect(
      detectProviderLabel("llm", "http://localhost:11434/v1"),
    ).toMatchObject({ providerId: "ollama", label: "Ollama" });
    expect(
      detectProviderLabel("llm", "http://127.0.0.1:8000/v1"),
    ).toMatchObject({ providerId: "vllm", label: "VLLM" });
  });

  it("detects the Teajoin Tushare proxy as a data source provider", () => {
    const detection = detectProviderLabel("data_source", "https://teajoin.com");

    expect(detection).toMatchObject({
      providerId: "tushare",
      label: "Tushare",
      isCustom: false,
    });
    expect(
      providerNameForCategory(
        {
          id: "data_source",
          title: "数据源配置",
          providerType: "market_data",
          defaultProviderName: "data_source",
          urlLabel: "数据源 URL",
          tokenPlaceholder: "token",
        },
        detection,
      ),
    ).toBe("tushare");
  });

  it("prefers configured provider versions over empty active versions", () => {
    const selected = chooseProviderForCategory(
      [
        {
          version_id: "provider-llm-active-empty",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          enabled: true,
          lifecycle: "active",
          base_url: "https://api.deepseek.com/v1",
          model_name: "deepseek-chat",
          secret_metadata: null,
        },
        {
          version_id: "provider-llm-draft-configured",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          enabled: true,
          lifecycle: "draft",
          base_url: "https://api.deepseek.com/v1",
          model_name: "deepseek-chat",
          secret_metadata: {
            configured: true,
            last_four: "1234",
            provider_name: "provider-llm-draft-configured",
            secret_name: "api_key",
            status: "active",
            updated_at: "2026-07-01T00:00:00Z",
            version_id: "sec-1",
          },
        },
      ],
      "llm",
    );

    expect(selected?.version_id).toBe("provider-llm-draft-configured");
  });

  it("uses the most recently saved configured provider version on startup", () => {
    const selected = chooseProviderForCategory(
      [
        {
          version_id: "provider-llm-active-old",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          enabled: true,
          lifecycle: "active",
          base_url: "https://api.deepseek.com/v1",
          model_name: "deepseek-chat",
          secret_metadata: {
            configured: true,
            last_four: "1111",
            provider_name: "provider-llm-active-old",
            secret_name: "api_key",
            status: "active",
            updated_at: "2026-07-01T00:00:00Z",
            version_id: "sec-old",
          },
        },
        {
          version_id: "provider-llm-draft-new",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          enabled: true,
          lifecycle: "draft",
          base_url: "https://api.deepseek.com/v1",
          model_name: "deepseek-chat",
          secret_metadata: {
            configured: true,
            last_four: "2222",
            provider_name: "provider-llm-draft-new",
            secret_name: "api_key",
            status: "active",
            updated_at: "2026-07-01T01:00:00Z",
            version_id: "sec-new",
          },
        },
      ],
      "llm",
    );

    expect(selected?.version_id).toBe("provider-llm-draft-new");
  });
});
