/**
 * @fileoverview Provider Settings secret handling tests.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
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
  fireEvent.click(screen.getByRole("button", { name: "Save secret" }));

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
  fireEvent.click(screen.getByRole("button", { name: "Save secret" }));

  await screen.findByRole("alert");
  expect(screen.queryByText(/abcdef1234567890/)).not.toBeInTheDocument();
});
