/**
 * @fileoverview Provider Settings secret handling tests.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ProviderSettingsPanel } from "./provider-settings-panel";

afterEach(cleanup);

test("provider settings writes secret without rendering plaintext after save", async () => {
  const saveSecret = vi.fn().mockResolvedValue({
    configured: true,
    last_four: "7890",
    version_id: "sec-1",
    status: "active",
    updated_at: "2026-06-22T10:00:00Z",
    provider_name: "tushare",
    secret_name: "api_token",
  });

  render(
    <ProviderSettingsPanel
      providers={[
        {
          version_id: "provider-tushare-1",
          provider_name: "tushare",
          provider_type: "market_data",
          base_url: "https://api.tushare.pro",
          enabled: true,
          lifecycle: "draft",
          secret_metadata: null,
        },
      ]}
      saveSecret={saveSecret}
    />,
  );

  fireEvent.change(screen.getByLabelText("tushare secret"), {
    target: { value: "abcdef1234567890" },
  });
  const section = screen.getByRole("heading", { name: "数据源配置" }).closest("section");
  expect(section).not.toBeNull();
  fireEvent.click(
    within(section as HTMLElement).getByRole("button", { name: "保存配置" }),
  );

  await waitFor(() => expect(saveSecret).toHaveBeenCalled());
  expect(screen.queryByDisplayValue("abcdef1234567890")).not.toBeInTheDocument();
  expect(screen.getByText("•••• 7890")).toBeInTheDocument();
});

test("provider settings never renders a rejected secret in an error", async () => {
  const saveSecret = vi
    .fn()
    .mockRejectedValue(new Error("request failed token=abcdef1234567890"));

  render(
    <ProviderSettingsPanel
      providers={[
        {
          version_id: "provider-tushare-1",
          provider_name: "tushare",
          provider_type: "market_data",
          base_url: "https://api.tushare.pro",
          enabled: true,
          lifecycle: "draft",
          secret_metadata: null,
        },
      ]}
      saveSecret={saveSecret}
    />,
  );

  fireEvent.change(screen.getByLabelText("tushare secret"), {
    target: { value: "abcdef1234567890" },
  });
  const section = screen.getByRole("heading", { name: "数据源配置" }).closest("section");
  expect(section).not.toBeNull();
  fireEvent.click(
    within(section as HTMLElement).getByRole("button", { name: "保存配置" }),
  );

  await screen.findByRole("alert");
  expect(screen.queryByText(/abcdef1234567890/)).not.toBeInTheDocument();
});

test("provider settings creates a draft before writing a secret for active providers", async () => {
  const createProvider = vi.fn().mockResolvedValue({
    base_url: "https://api.deepseek.com/v1",
    enabled: true,
    lifecycle: "draft",
    model_name: "deepseek-chat",
    non_sensitive_config: {
      detected_label: "DeepSeek",
      detected_provider: "deepseek",
      is_custom_provider: false,
      provider_category: "llm",
    },
    owner_id: "local-admin",
    provider_name: "llm",
    provider_type: "llm",
    version_id: "provider-llm-new-draft",
  });
  const saveSecret = vi.fn().mockResolvedValue({
    configured: true,
    last_four: "5555",
    version_id: "sec-llm-new",
    status: "active",
    updated_at: "2026-07-01T10:00:00Z",
    provider_name: "provider-llm-new-draft",
    secret_name: "api_key",
  });

  render(
    <ProviderSettingsPanel
      providers={[]}
      createProvider={createProvider}
      saveSecret={saveSecret}
    />,
  );

  fireEvent.change(screen.getByLabelText("llm secret"), {
    target: { value: "sk-deepseek-test-5555" },
  });
  const section = screen.getByRole("heading", { name: "LLM 配置" }).closest("section");
  expect(section).not.toBeNull();
  fireEvent.click(
    within(section as HTMLElement).getByRole("button", { name: "保存配置" }),
  );

  await waitFor(() =>
    expect(saveSecret).toHaveBeenCalledWith(
      "provider-llm-new-draft",
      "api_key",
      "sk-deepseek-test-5555",
    ),
  );
  expect(createProvider).toHaveBeenCalledWith(
    expect.objectContaining({
      base_url: "https://api.deepseek.com/v1",
      lifecycle: "draft",
      model_name: "deepseek-chat",
      provider_name: "llm",
      provider_type: "llm",
    }),
  );
  expect(screen.getByText("•••• 5555")).toBeInTheDocument();
});

test("provider settings creates a provider when randomUUID is unavailable", async () => {
  const createProvider = vi.fn().mockResolvedValue({
    base_url: "https://api.minimaxi.com/v1",
    enabled: true,
    lifecycle: "draft",
    model_name: "MiniMax-M3",
    non_sensitive_config: {
      detected_label: "Minimax",
      detected_provider: "minimax",
      is_custom_provider: false,
      provider_category: "llm",
    },
    owner_id: "local-admin",
    provider_name: "llm",
    provider_type: "llm",
    version_id: "provider-llm-minimax-fallback",
  });
  const saveSecret = vi.fn().mockResolvedValue({
    configured: true,
    last_four: "Nup8",
    version_id: "sec-minimax-fallback",
    status: "active",
    updated_at: "2026-07-09T10:00:00Z",
    provider_name: "provider-llm-minimax-fallback",
    secret_name: "api_key",
  });
  vi.stubGlobal("crypto", {});

  render(
    <ProviderSettingsPanel
      providers={[]}
      createProvider={createProvider}
      saveSecret={saveSecret}
    />,
  );

  const section = screen.getByRole("heading", { name: "LLM 配置" }).closest("section");
  expect(section).not.toBeNull();
  fireEvent.change(screen.getByLabelText("LLM 配置 provider"), {
    target: { value: "minimax" },
  });
  fireEvent.change(screen.getByLabelText("llm secret"), {
    target: { value: "sk-minimax-test-Nup8" },
  });
  fireEvent.click(
    within(section as HTMLElement).getByRole("button", { name: "保存配置" }),
  );

  await waitFor(() => expect(createProvider).toHaveBeenCalled());
  expect(saveSecret).toHaveBeenCalledWith(
    "provider-llm-minimax-fallback",
    "api_key",
    "sk-minimax-test-Nup8",
  );
});

test("provider settings maps the Teajoin data source URL to Tushare", async () => {
  const createProvider = vi.fn().mockResolvedValue({
    base_url: "https://teajoin.com",
    enabled: true,
    lifecycle: "draft",
    model_name: null,
    non_sensitive_config: {
      detected_label: "Tushare",
      detected_provider: "tushare",
      is_custom_provider: false,
      provider_category: "data_source",
    },
    owner_id: "local-admin",
    provider_name: "tushare",
    provider_type: "market_data",
    version_id: "provider-data-source-teajoin",
  });
  const saveSecret = vi.fn().mockResolvedValue({
    configured: true,
    last_four: "984f",
    version_id: "sec-tushare-teajoin",
    status: "active",
    updated_at: "2026-07-09T10:00:00Z",
    provider_name: "provider-data-source-teajoin",
    secret_name: "api_token",
  });

  render(
    <ProviderSettingsPanel
      providers={[]}
      createProvider={createProvider}
      saveSecret={saveSecret}
    />,
  );

  const section = screen.getByRole("heading", { name: "数据源配置" }).closest("section");
  expect(section).not.toBeNull();
  fireEvent.change(screen.getByLabelText("数据源配置 provider"), {
    target: { value: "custom" },
  });
  fireEvent.change(screen.getByLabelText("数据源配置 URL"), {
    target: { value: "https://teajoin.com" },
  });
  fireEvent.change(screen.getByLabelText("data_source secret"), {
    target: { value: "tushare-token-984f" },
  });
  fireEvent.click(
    within(section as HTMLElement).getByRole("button", { name: "保存配置" }),
  );

  await waitFor(() => expect(createProvider).toHaveBeenCalled());
  expect(createProvider).toHaveBeenCalledWith(
    expect.objectContaining({
      base_url: "https://teajoin.com",
      provider_name: "tushare",
      provider_type: "market_data",
    }),
  );
  expect(saveSecret).toHaveBeenCalledWith(
    "provider-data-source-teajoin",
    "api_token",
    "tushare-token-984f",
  );
});

test("provider settings renders separate category panels with detected tags", () => {
  render(
    <ProviderSettingsPanel
      providers={[
        {
          version_id: "provider-llm-deepseek",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          detected_provider: "deepseek",
          detected_label: "DeepSeek",
          is_custom_provider: false,
          base_url: "https://api.deepseek.com/v1",
          model_name: "deepseek-chat",
          enabled: true,
          lifecycle: "draft",
          secret_metadata: null,
        },
        {
          version_id: "provider-search-custom",
          provider_name: "web_search",
          provider_type: "websearch",
          provider_category: "web_search",
          detected_provider: "custom",
          detected_label: "Custom",
          is_custom_provider: true,
          base_url: "https://search.internal.example",
          enabled: true,
          lifecycle: "draft",
          secret_metadata: null,
        },
      ]}
    />,
  );

  expect(screen.getByRole("heading", { name: "LLM 配置" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "网页搜索配置" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "数据源配置" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "向量化模型配置" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Rerank 配置" })).toBeInTheDocument();
  expect(screen.getAllByText("DeepSeek").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Custom").length).toBeGreaterThan(0);
  expect(screen.queryByText("管理员 token")).not.toBeInTheDocument();
  expect(screen.queryByText("CSRF token")).not.toBeInTheDocument();
});

test("provider settings constrains long editable values inside provider cards", () => {
  render(
    <ProviderSettingsPanel
      providers={[
        {
          version_id:
            "provider-llm-with-a-very-long-version-id-that-should-never-expand-the-card",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          detected_provider: "minimax",
          detected_label: "Minimax",
          is_custom_provider: false,
          base_url:
            "https://platform.minimaxi.com/api/v1/text/chatcompletion_pro_with_a_very_long_path",
          model_name: "MiniMax-M3-with-a-very-long-model-name-for-layout-regression",
          enabled: true,
          lifecycle: "draft",
          secret_metadata: {
            configured: true,
            last_four: "long-tail-that-should-truncate",
            version_id: "sec-llm-long",
            status: "active",
            updated_at: "2026-07-09T10:00:00Z",
            provider_name: "provider-llm-long",
            secret_name: "api_key",
          },
        },
      ]}
    />,
  );

  const section = screen.getByRole("heading", { name: "LLM 配置" }).closest("section");
  expect(section).not.toBeNull();
  expect(section as HTMLElement).toHaveClass("min-w-0", "overflow-hidden");
  expect(screen.getByLabelText("LLM 配置 URL")).toHaveClass(
    "min-w-0",
    "overflow-hidden",
    "text-ellipsis",
  );
  expect(screen.getByLabelText("LLM 配置 model")).toHaveClass(
    "min-w-0",
    "overflow-hidden",
    "text-ellipsis",
  );
  expect(screen.getByLabelText("llm secret")).toHaveClass(
    "min-w-0",
    "overflow-hidden",
    "text-ellipsis",
  );
  expect(screen.getByText("•••• long-tail-that-should-truncate")).toHaveClass(
    "truncate",
  );
});

test("provider settings preserves saved preset URLs before allowing custom URLs", () => {
  render(
    <ProviderSettingsPanel
      providers={[
        {
          version_id: "provider-llm-minimax-old-url",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          detected_provider: "minimax",
          detected_label: "Minimax",
          is_custom_provider: false,
          base_url: "https://platform.minimaxi.com",
          model_name: "MiniMax-M3",
          enabled: true,
          lifecycle: "draft",
          secret_metadata: null,
        },
      ]}
    />,
  );

  const providerSelect = screen.getByLabelText("LLM 配置 provider");
  const urlInput = screen.getByLabelText("LLM 配置 URL");
  expect(providerSelect).toHaveValue("minimax");
  expect(urlInput).toHaveValue("https://platform.minimaxi.com");
  expect(urlInput).toBeDisabled();

  fireEvent.change(providerSelect, { target: { value: "custom" } });

  expect(urlInput).not.toBeDisabled();
});

test("provider settings renders active provider as active after page reload", () => {
  render(
    <ProviderSettingsPanel
      providers={[
        {
          version_id: "provider-llm-active",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          detected_provider: "deepseek",
          detected_label: "DeepSeek",
          is_custom_provider: false,
          base_url: "https://api.deepseek.com/v1",
          model_name: "deepseek-chat",
          enabled: true,
          lifecycle: "active",
          secret_metadata: {
            configured: true,
            last_four: "5555",
            version_id: "sec-llm-active",
            status: "active",
            updated_at: "2026-07-01T10:00:00Z",
            provider_name: "provider-llm-active",
            secret_name: "api_key",
          },
        },
      ]}
    />,
  );

  const section = screen.getByRole("heading", { name: "LLM 配置" }).closest("section");
  expect(section).not.toBeNull();
  expect(section as HTMLElement).toHaveTextContent("已激活");
  expect(within(section as HTMLElement).queryByText("not tested")).not.toBeInTheDocument();
  expect(within(section as HTMLElement).queryByText("provider-llm-active")).not
    .toBeInTheDocument();
});

test("provider settings updates the selected category after activation", async () => {
  const activate = vi.fn().mockResolvedValue({
    base_url: "https://api.deepseek.com/v1",
    enabled: true,
    lifecycle: "active",
    model_name: "deepseek-chat",
    non_sensitive_config: {
      detected_label: "DeepSeek",
      detected_provider: "deepseek",
      is_custom_provider: false,
      provider_category: "llm",
    },
    owner_id: "local-admin",
    provider_name: "llm",
    provider_type: "llm",
    version_id: "provider-llm-draft",
  });

  render(
    <ProviderSettingsPanel
      providers={[
        {
          version_id: "provider-llm-draft",
          provider_name: "llm",
          provider_type: "llm",
          provider_category: "llm",
          detected_provider: "deepseek",
          detected_label: "DeepSeek",
          is_custom_provider: false,
          base_url: "https://api.deepseek.com/v1",
          model_name: "deepseek-chat",
          enabled: true,
          lifecycle: "draft",
          secret_metadata: {
            configured: true,
            last_four: "5555",
            version_id: "sec-llm-draft",
            status: "active",
            updated_at: "2026-07-01T10:00:00Z",
            provider_name: "provider-llm-draft",
            secret_name: "api_key",
          },
        },
      ]}
      activate={activate}
    />,
  );

  const section = screen.getByRole("heading", { name: "LLM 配置" }).closest("section");
  expect(section).not.toBeNull();
  fireEvent.click(
    within(section as HTMLElement).getByRole("button", { name: "激活" }),
  );

  await waitFor(() => expect(activate).toHaveBeenCalledWith("provider-llm-draft"));
  expect(section as HTMLElement).toHaveTextContent("已激活");
  expect(within(section as HTMLElement).queryByText("not tested")).not.toBeInTheDocument();
  expect(within(section as HTMLElement).queryByText("provider-llm-draft")).not
    .toBeInTheDocument();
});
