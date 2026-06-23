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
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="providers-title">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 id="providers-title">Provider 密钥配置</h1>
        </div>
        <div className="status-strip">
          <span>write-only secret</span>
          <span>{providers.length} configs</span>
        </div>
      </section>
      {error ? (
        <div className="notice-panel" role="alert">{error}</div>
      ) : null}
      <ProviderSettingsPanel providers={providers} />
    </main>
  );
}
