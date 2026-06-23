"use client";

/**
 * @fileoverview Write-only Provider Settings panel for encrypted API secrets.
 */

import { useState } from "react";

import {
  configureLocalAdminSession,
  saveProviderSecret,
  testProviderConfig,
  type ProviderConfigSummary,
  type ProviderHealthResult,
  type ProviderSecretMetadata,
} from "@/lib/api";

type ProviderSettingsPanelProps = {
  providers: ProviderConfigSummary[];
  saveSecret?: (
    providerConfigId: string,
    secretName: string,
    secretValue: string,
  ) => Promise<ProviderSecretMetadata>;
  testConnection?: (providerConfigId: string) => Promise<ProviderHealthResult>;
};

/** Renders encrypted provider credential controls and real health checks. */
export function ProviderSettingsPanel({
  providers,
  saveSecret = saveProviderSecret,
  testConnection = testProviderConfig,
}: ProviderSettingsPanelProps) {
  const [secretInputs, setSecretInputs] = useState<Record<string, string>>({});
  const [metadata, setMetadata] = useState<
    Record<string, ProviderSecretMetadata | null>
  >(
    Object.fromEntries(
      providers.map((provider) => [
        provider.version_id,
        provider.secret_metadata,
      ]),
    ),
  );
  const [health, setHealth] = useState<
    Record<string, ProviderHealthResult | null>
  >({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [adminToken, setAdminToken] = useState("");
  const [csrfToken, setCsrfToken] = useState("");
  const [sessionReady, setSessionReady] = useState(false);

  function saveAdminSession() {
    if (!adminToken || !csrfToken) {
      return;
    }
    configureLocalAdminSession(adminToken, csrfToken);
    setAdminToken("");
    setCsrfToken("");
    setSessionReady(true);
  }

  async function handleSave(provider: ProviderConfigSummary) {
    const secretValue = secretInputs[provider.version_id] ?? "";
    if (!secretValue) {
      setErrors((current) => ({
        ...current,
        [provider.version_id]: "请输入 Provider 密钥。",
      }));
      return;
    }
    setBusy((current) => ({ ...current, [provider.version_id]: true }));
    setErrors((current) => ({ ...current, [provider.version_id]: null }));
    try {
      const result = await saveSecret(
        provider.version_id,
        defaultSecretName(provider.provider_name),
        secretValue,
      );
      setMetadata((current) => ({
        ...current,
        [provider.version_id]: result,
      }));
    } catch {
      setErrors((current) => ({
        ...current,
        [provider.version_id]:
          "保存失败，请检查管理员会话、Provider 配置和后端日志。",
      }));
    } finally {
      setSecretInputs((current) => ({
        ...current,
        [provider.version_id]: "",
      }));
      setBusy((current) => ({ ...current, [provider.version_id]: false }));
    }
  }

  async function handleTest(provider: ProviderConfigSummary) {
    setSecretInputs((current) => ({
      ...current,
      [provider.version_id]: "",
    }));
    setBusy((current) => ({ ...current, [provider.version_id]: true }));
    setErrors((current) => ({ ...current, [provider.version_id]: null }));
    try {
      const result = await testConnection(provider.version_id);
      setHealth((current) => ({
        ...current,
        [provider.version_id]: result,
      }));
    } catch {
      setErrors((current) => ({
        ...current,
        [provider.version_id]:
          "测试失败，请检查管理员会话、网络和 Provider 配置。",
      }));
    } finally {
      setBusy((current) => ({ ...current, [provider.version_id]: false }));
    }
  }

  return (
    <section className="panel provider-settings" aria-labelledby="provider-settings-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Local admin</p>
          <h2 id="provider-settings-title">Provider 设置</h2>
        </div>
        <span>{providers.length} configs</span>
      </div>

      <div className="provider-admin-session">
        <div>
          <strong>管理员会话</strong>
          <span>凭据仅保存在当前浏览器标签页。</span>
        </div>
        <label className="form-field">
          <span>管理员 token</span>
          <input
            aria-label="local admin token"
            autoComplete="off"
            onChange={(event) => setAdminToken(event.target.value)}
            type="password"
            value={adminToken}
          />
        </label>
        <label className="form-field">
          <span>CSRF token</span>
          <input
            aria-label="CSRF token"
            autoComplete="off"
            onChange={(event) => setCsrfToken(event.target.value)}
            type="password"
            value={csrfToken}
          />
        </label>
        <button
          className="secondary-button"
          disabled={!adminToken || !csrfToken}
          onClick={saveAdminSession}
          type="button"
        >
          {sessionReady ? "会话已启用" : "仅在此标签页启用"}
        </button>
      </div>

      {providers.length === 0 ? (
        <div className="empty-state compact">暂无 Provider 配置版本</div>
      ) : (
        <div className="provider-settings-list">
          {providers.map((provider) => {
            const providerMetadata = metadata[provider.version_id];
            const providerHealth = health[provider.version_id];
            const isBusy = busy[provider.version_id] ?? false;
            const error = errors[provider.version_id];
            return (
              <article className="provider-setting-card" key={provider.version_id}>
                <div className="provider-setting-header">
                  <div>
                    <strong>{provider.provider_name}</strong>
                    <span>
                      {provider.provider_type} · {provider.lifecycle}
                    </span>
                  </div>
                  <span
                    className={`badge ${
                      providerHealth
                        ? `provider-${providerHealth.status}`
                        : "provider-not-configured"
                    }`}
                  >
                    {providerHealth?.status ?? "not tested"}
                  </span>
                </div>

                <label className="form-field">
                  <span>{provider.provider_name} secret</span>
                  <input
                    aria-label={`${provider.provider_name} secret`}
                    autoComplete="new-password"
                    disabled={isBusy}
                    onChange={(event) =>
                      setSecretInputs((current) => ({
                        ...current,
                        [provider.version_id]: event.target.value,
                      }))
                    }
                    type="password"
                    value={secretInputs[provider.version_id] ?? ""}
                  />
                </label>

                <div className="provider-setting-actions">
                  <button
                    className="primary-button"
                    disabled={isBusy}
                    onClick={() => handleSave(provider)}
                    type="button"
                  >
                    {isBusy ? "Working…" : "Save secret"}
                  </button>
                  <button
                    className="secondary-button"
                    disabled={isBusy}
                    onClick={() => handleTest(provider)}
                    type="button"
                  >
                    Test connection
                  </button>
                  <span className="provider-secret-mask">
                    {providerMetadata?.configured
                      ? `•••• ${providerMetadata.last_four}`
                      : "未配置"}
                  </span>
                </div>

                {providerHealth ? (
                  <p className="helper-text">
                    {providerHealth.status} · {providerHealth.latency_ms ?? "--"} ms
                  </p>
                ) : null}
                {error ? (
                  <p className="form-error" role="alert">
                    {error}
                  </p>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function defaultSecretName(providerName: string): string {
  if (providerName.toLowerCase().includes("tushare")) {
    return "api_token";
  }
  return "api_key";
}
