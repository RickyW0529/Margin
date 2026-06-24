/**
 * @fileoverview Provider settings page.
 */

import { ProviderSettingsPanel } from "@/components/provider-settings-panel";
import { fetchProviderConfigs, type ProviderConfigSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Renders write-only Provider secret settings backed by the v0.2 config API. */
export default async function ProviderSettingsPage() {
  let providers: ProviderConfigSummary[] = [];
  let error: string | null = null;

  try {
    providers = await fetchProviderConfigs();
  } catch {
    error = "Provider 配置暂时不可用";
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-10 py-9">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Settings
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            Provider 密钥配置
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            只写录入，永不回显明文；本地 Secret Store 加密保存。
          </p>
        </div>
        <div className="flex gap-2">
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            write-only secret
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {providers.length} configs
          </span>
        </div>
      </header>
      {error ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          {error}
        </div>
      ) : null}
      <ProviderSettingsPanel providers={providers} />
    </main>
  );
}
