"use client";

/**
 * @fileoverview Write-only Provider Settings panel for encrypted API secrets.
 */

import { useState } from "react";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  activateProviderConfig,
  configureLocalAdminSession,
  saveProviderSecret,
  testProviderConfig,
  type ProviderConfigSummary,
  type ProviderHealthResult,
  type ProviderSecretMetadata,
  type VersionedConfigRecord,
} from "@/lib/api";

type ProviderSettingsPanelProps = {
  providers: ProviderConfigSummary[];
  saveSecret?: (
    providerConfigId: string,
    secretName: string,
    secretValue: string,
  ) => Promise<ProviderSecretMetadata>;
  testConnection?: (
    providerConfigId: string,
  ) => Promise<ProviderHealthResult>;
  activate?: (providerConfigId: string) => Promise<VersionedConfigRecord>;
};

function healthTone(status: string): BadgeProps["tone"] {
  if (status === "ok") {
    return "positive";
  }
  if (status === "failed") {
    return "negative";
  }
  return "muted";
}

/** Renders encrypted provider credential controls, health checks and activation. */
export function ProviderSettingsPanel({
  providers,
  saveSecret = saveProviderSecret,
  testConnection = testProviderConfig,
  activate = activateProviderConfig,
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
  const [success, setSuccess] = useState<Record<string, string | null>>({});
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
    setSuccess((current) => ({ ...current, [provider.version_id]: null }));
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
      setSuccess((current) => ({
        ...current,
        [provider.version_id]: "密钥已加密保存。",
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
    setBusy((current) => ({ ...current, [provider.version_id]: true }));
    setErrors((current) => ({ ...current, [provider.version_id]: null }));
    setSuccess((current) => ({ ...current, [provider.version_id]: null }));
    try {
      const result = await testConnection(provider.version_id);
      setHealth((current) => ({ ...current, [provider.version_id]: result }));
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

  async function handleActivate(provider: ProviderConfigSummary) {
    setBusy((current) => ({ ...current, [provider.version_id]: true }));
    setErrors((current) => ({ ...current, [provider.version_id]: null }));
    setSuccess((current) => ({ ...current, [provider.version_id]: null }));
    try {
      await activate(provider.version_id);
      setSuccess((current) => ({
        ...current,
        [provider.version_id]: "Provider 配置已激活。",
      }));
    } catch {
      setErrors((current) => ({
        ...current,
        [provider.version_id]: "激活失败，请先通过健康检查再激活。",
      }));
    } finally {
      setBusy((current) => ({ ...current, [provider.version_id]: false }));
    }
  }

  return (
    <Card aria-labelledby="provider-settings-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Local admin
          </p>
          <CardTitle id="provider-settings-title" className="mt-1">
            Provider 设置
          </CardTitle>
        </div>
        <span className="text-xs text-muted-foreground">
          {providers.length} configs
        </span>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 rounded-md border border-border bg-muted/40 p-4 md:grid-cols-[1fr_1fr_auto]">
          <div className="grid gap-1.5">
            <Label>管理员 token</Label>
            <Input
              aria-label="local admin token"
              autoComplete="off"
              type="password"
              value={adminToken}
              onChange={(event) => setAdminToken(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label>CSRF token</Label>
            <Input
              aria-label="CSRF token"
              autoComplete="off"
              type="password"
              value={csrfToken}
              onChange={(event) => setCsrfToken(event.target.value)}
            />
          </div>
          <Button
            variant="secondary"
            disabled={!adminToken || !csrfToken}
            onClick={saveAdminSession}
            type="button"
            className="self-end"
          >
            {sessionReady ? "会话已启用" : "仅在此标签页启用"}
          </Button>
        </div>

        {providers.length === 0 ? (
          <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
            暂无 Provider 配置版本
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {providers.map((provider) => {
              const providerMetadata = metadata[provider.version_id];
              const providerHealth = health[provider.version_id];
              const isBusy = busy[provider.version_id] ?? false;
              const error = errors[provider.version_id];
              const ok = success[provider.version_id];
              return (
                <article
                  key={provider.version_id}
                  className="grid gap-3 rounded-md border border-border p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="grid min-w-0 gap-0.5">
                      <strong className="truncate text-sm text-foreground">
                        {provider.provider_name}
                      </strong>
                      <span className="truncate text-xs text-muted-foreground">
                        {provider.provider_type} · {provider.lifecycle}
                      </span>
                    </div>
                    <Badge
                      tone={healthTone(
                        providerHealth?.status ?? "not_configured",
                      )}
                    >
                      {providerHealth?.status ?? "not tested"}
                    </Badge>
                  </div>

                  <div className="grid gap-1.5">
                    <Label>{provider.provider_name} secret</Label>
                    <Input
                      aria-label={`${provider.provider_name} secret`}
                      autoComplete="new-password"
                      disabled={isBusy}
                      type="password"
                      value={secretInputs[provider.version_id] ?? ""}
                      onChange={(event) =>
                        setSecretInputs((current) => ({
                          ...current,
                          [provider.version_id]: event.target.value,
                        }))
                      }
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      loading={isBusy}
                      onClick={() => handleSave(provider)}
                      type="button"
                    >
                      Save secret
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={isBusy}
                      onClick={() => handleTest(provider)}
                      type="button"
                    >
                      Test connection
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={isBusy}
                      onClick={() => handleActivate(provider)}
                      type="button"
                    >
                      激活
                    </Button>
                    <span className="font-mono text-xs text-muted-foreground">
                      {providerMetadata?.configured
                        ? `•••• ${providerMetadata.last_four}`
                        : "未配置"}
                    </span>
                  </div>

                  {providerHealth ? (
                    <p className="text-xs text-muted-foreground">
                      {providerHealth.status} ·{" "}
                      {providerHealth.latency_ms ?? "--"} ms
                    </p>
                  ) : null}
                  {error ? (
                    <p className="text-xs text-negative" role="alert">
                      {error}
                    </p>
                  ) : null}
                  {ok ? (
                    <p className="text-xs text-positive" role="status">
                      {ok}
                    </p>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function defaultSecretName(providerName: string): string {
  if (providerName.toLowerCase().includes("tushare")) {
    return "api_token";
  }
  return "api_key";
}
