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
  expect(screen.getByText("DeepSeek")).toBeInTheDocument();
  expect(screen.getAllByText("Custom").length).toBeGreaterThan(0);
});
