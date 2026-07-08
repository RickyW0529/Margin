"use client";

/**
 * @fileoverview Category-based write-only Provider Settings panel.
 */

import { useMemo, useState } from "react";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  activateProviderConfig,
  createProviderConfig,
  saveProviderSecret,
  testProviderConfig,
  type ProviderConfigSummary,
  type ProviderHealthResult,
  type ProviderSecretMetadata,
  type VersionedConfigRecord,
} from "@/lib/api";
import {
  categoryForProvider,
  chooseProviderForCategory,
  defaultSecretName,
  detectProviderLabel,
  displayDetection,
  providerNameForCategory,
  PROVIDER_CATEGORIES,
  type ProviderCategoryDefinition,
  type ProviderCategoryId,
} from "@/lib/provider-settings";

type ProviderSettingsPanelProps = {
  providers: ProviderConfigSummary[];
  createProvider?: (body: Record<string, unknown>) => Promise<VersionedConfigRecord>;
  saveSecret?: (
    providerConfigId: string,
    secretName: string,
    secretValue: string,
  ) => Promise<ProviderSecretMetadata>;
  testConnection?: (providerConfigId: string) => Promise<ProviderHealthResult>;
  activate?: (providerConfigId: string) => Promise<VersionedConfigRecord>;
};

type DraftState = {
  url: string;
  model: string;
  secret: string;
};

function healthTone(status: string): BadgeProps["tone"] {
  if (status === "ok" || status === "active") {
    return "positive";
  }
  if (status === "failed") {
    return "negative";
  }
  return "muted";
}

/** Renders encrypted provider credential controls grouped by provider category. */
export function ProviderSettingsPanel({
  providers,
  createProvider = createProviderConfig,
  saveSecret = saveProviderSecret,
  testConnection = testProviderConfig,
  activate = activateProviderConfig,
}: ProviderSettingsPanelProps) {
  const [configs, setConfigs] = useState<ProviderConfigSummary[]>(providers);
  const [selectedVersionIds, setSelectedVersionIds] = useState<
    Partial<Record<ProviderCategoryId, string>>
  >({});
  const initialDrafts = useMemo(() => buildInitialDrafts(providers), [providers]);
  const [drafts, setDrafts] = useState<Record<ProviderCategoryId, DraftState>>(
    initialDrafts,
  );
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
  const [health, setHealth] = useState<Record<string, ProviderHealthResult | null>>(
    {},
  );
  const [busy, setBusy] = useState<Record<ProviderCategoryId, boolean>>({
    data_source: false,
    embedding: false,
    llm: false,
    rerank: false,
    web_search: false,
  });
  const [errors, setErrors] = useState<Record<ProviderCategoryId, string | null>>({
    data_source: null,
    embedding: null,
    llm: null,
    rerank: null,
    web_search: null,
  });
  const [success, setSuccess] = useState<Record<ProviderCategoryId, string | null>>({
    data_source: null,
    embedding: null,
    llm: null,
    rerank: null,
    web_search: null,
  });

  async function ensureConfig(
    category: ProviderCategoryDefinition,
  ): Promise<ProviderConfigSummary> {
    const existing = chooseProviderFromSelection(
      configs,
      category.id,
      selectedVersionIds[category.id],
    );
    const draft = drafts[category.id];
    const urlChanged = draft.url.trim() !== (existing?.base_url ?? "");
    const modelChanged = draft.model.trim() !== (existing?.model_name ?? "");
    if (
      existing &&
      existing.lifecycle !== "active" &&
      !urlChanged &&
      !modelChanged
    ) {
      return existing;
    }

    const detection = detectProviderLabel(category.id, draft.url);
    const providerName = providerNameForCategory(category, detection);
    const created = await createProvider({
      base_url: draft.url.trim() || null,
      enabled: true,
      lifecycle: "draft",
      model_name: draft.model.trim() || null,
      non_sensitive_config: {
        allow_custom_base_url: detection.isCustom,
        detected_provider: detection.providerId,
        detected_label: detection.label,
        is_custom_provider: detection.isCustom,
        provider_category: category.id,
      },
      owner_id: "local-admin",
      provider_name: providerName,
      provider_type: category.providerType,
      version_id: `provider-${category.id}-${globalThis.crypto.randomUUID()}`,
    });
    const summary = providerSummaryFromRecord(created, category, detection);
    setConfigs((current) => [
      ...current.filter((provider) => provider.version_id !== summary.version_id),
      summary,
    ]);
    setSelectedVersionIds((current) => ({
      ...current,
      [category.id]: summary.version_id,
    }));
    return summary;
  }

  async function handleSave(category: ProviderCategoryDefinition) {
    const draft = drafts[category.id];
    const detection = detectProviderLabel(category.id, draft.url);
    if (!draft.url.trim()) {
      setErrors((current) => ({
        ...current,
        [category.id]: "请输入 API URL。",
      }));
      return;
    }
    if (!draft.secret && !(category.id === "data_source" && detection.providerId === "akshare")) {
      setErrors((current) => ({
        ...current,
        [category.id]: "请输入 API Token。",
      }));
      return;
    }
    setBusy((current) => ({ ...current, [category.id]: true }));
    setErrors((current) => ({ ...current, [category.id]: null }));
    setSuccess((current) => ({ ...current, [category.id]: null }));
    try {
      const config = await ensureConfig(category);
      if (draft.secret) {
        const result = await saveSecret(
          config.version_id,
          defaultSecretName(category.id, config.provider_name),
          draft.secret,
        );
        setMetadata((current) => ({ ...current, [config.version_id]: result }));
      }
      setDrafts((current) => ({
        ...current,
        [category.id]: { ...current[category.id], secret: "" },
      }));
      setSuccess((current) => ({
        ...current,
        [category.id]: "配置已保存。",
      }));
    } catch {
      setErrors((current) => ({
        ...current,
        [category.id]: "保存失败，请检查 URL 和后端日志。",
      }));
    } finally {
      setBusy((current) => ({ ...current, [category.id]: false }));
    }
  }

  async function handleTest(category: ProviderCategoryDefinition) {
    const provider = chooseProviderFromSelection(
      configs,
      category.id,
      selectedVersionIds[category.id],
    );
    if (!provider) {
      setErrors((current) => ({
        ...current,
        [category.id]: "请先保存配置。",
      }));
      return;
    }
    setBusy((current) => ({ ...current, [category.id]: true }));
    setErrors((current) => ({ ...current, [category.id]: null }));
    setSuccess((current) => ({ ...current, [category.id]: null }));
    try {
      const result = await testConnection(provider.version_id);
      setHealth((current) => ({ ...current, [provider.version_id]: result }));
    } catch {
      setErrors((current) => ({
        ...current,
        [category.id]: "测试失败，请检查网络和 Provider 配置。",
      }));
    } finally {
      setBusy((current) => ({ ...current, [category.id]: false }));
    }
  }

  async function handleActivate(category: ProviderCategoryDefinition) {
    const provider = chooseProviderFromSelection(
      configs,
      category.id,
      selectedVersionIds[category.id],
    );
    if (!provider) {
      setErrors((current) => ({
        ...current,
        [category.id]: "请先保存配置。",
      }));
      return;
    }
    setBusy((current) => ({ ...current, [category.id]: true }));
    setErrors((current) => ({ ...current, [category.id]: null }));
    setSuccess((current) => ({ ...current, [category.id]: null }));
    try {
      const activated = await activate(provider.version_id);
      setConfigs((current) =>
        current.map((candidate) => {
          if (candidate.version_id === provider.version_id) {
            return {
              ...candidate,
              enabled: (activated.enabled as boolean | undefined) ?? candidate.enabled,
              lifecycle: (activated.lifecycle as string | undefined) ?? "active",
              secret_metadata:
                metadata[provider.version_id] ?? candidate.secret_metadata,
            };
          }
          if (
            categoryForProvider(candidate) === category.id &&
            candidate.lifecycle === "active"
          ) {
            return { ...candidate, lifecycle: "deprecated" };
          }
          return candidate;
        }),
      );
      setSuccess((current) => ({
        ...current,
        [category.id]: "Provider 配置已激活。",
      }));
    } catch {
      setErrors((current) => ({
        ...current,
        [category.id]: "激活失败，请先通过健康检查再激活。",
      }));
    } finally {
      setBusy((current) => ({ ...current, [category.id]: false }));
    }
  }

  return (
    <Card aria-labelledby="provider-settings-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            密钥配置
          </p>
          <CardTitle id="provider-settings-title" className="mt-1">
            数据源与模型密钥
          </CardTitle>
        </div>
        <span className="text-xs text-muted-foreground">
          {configs.length} 项配置
        </span>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-4 xl:grid-cols-2">
          {PROVIDER_CATEGORIES.map((category) => {
            const provider = chooseProviderFromSelection(
              configs,
              category.id,
              selectedVersionIds[category.id],
            );
            const draft = drafts[category.id];
            const detection = displayDetection(
              category.id,
              draft.url === (provider?.base_url ?? "") ? provider : null,
              draft.url,
            );
            return (
              <ProviderCategorySection
                key={category.id}
                category={category}
                detection={detection}
                draft={draft}
                error={errors[category.id]}
                health={provider ? health[provider.version_id] : null}
                isBusy={busy[category.id]}
                metadata={provider ? metadata[provider.version_id] : null}
                provider={provider}
                success={success[category.id]}
                onActivate={() => handleActivate(category)}
                onDraftChange={(next) =>
                  setDrafts((current) => ({
                    ...current,
                    [category.id]: { ...current[category.id], ...next },
                  }))
                }
                onSave={() => handleSave(category)}
                onTest={() => handleTest(category)}
              />
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

type ProviderCategorySectionProps = {
  category: ProviderCategoryDefinition;
  detection: { label: string; isCustom: boolean };
  draft: DraftState;
  error: string | null;
  health: ProviderHealthResult | null;
  isBusy: boolean;
  metadata: ProviderSecretMetadata | null;
  provider: ProviderConfigSummary | null;
  success: string | null;
  onActivate: () => void;
  onDraftChange: (next: Partial<DraftState>) => void;
  onSave: () => void;
  onTest: () => void;
};

function ProviderCategorySection({
  category,
  detection,
  draft,
  error,
  health,
  isBusy,
  metadata,
  provider,
  success,
  onActivate,
  onDraftChange,
  onSave,
  onTest,
}: ProviderCategorySectionProps) {
  const statusLabel =
    health?.status ?? (provider?.lifecycle === "active" ? "active" : "not tested");
  return (
    <section className="grid gap-4 rounded-md border border-border bg-card p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">
            {category.title}
          </h2>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {provider?.lifecycle ?? "未保存"} · {provider?.version_id ?? "new"}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <Badge tone={detection.isCustom ? "muted" : "positive"}>
            {detection.label}
          </Badge>
          <Badge tone={healthTone(statusLabel)}>
            {statusLabel}
          </Badge>
        </div>
      </header>

      <div className="grid gap-3">
        <div className="grid gap-1.5">
          <Label>{category.urlLabel}</Label>
          <Input
            aria-label={`${category.title} URL`}
            disabled={isBusy}
            placeholder="https://api.example.com/v1"
            value={draft.url}
            onChange={(event) => onDraftChange({ url: event.target.value })}
          />
        </div>
        {category.modelLabel ? (
          <div className="grid gap-1.5">
            <Label>{category.modelLabel}</Label>
            <Input
              aria-label={`${category.title} model`}
              disabled={isBusy}
              placeholder="model id"
              value={draft.model}
              onChange={(event) => onDraftChange({ model: event.target.value })}
            />
          </div>
        ) : null}
        <div className="grid gap-1.5">
          <Label>API Token</Label>
          <Input
            aria-label={`${provider?.provider_name ?? category.defaultProviderName} secret`}
            autoComplete="new-password"
            disabled={isBusy}
            placeholder={category.tokenPlaceholder}
            type="password"
            value={draft.secret}
            onChange={(event) => onDraftChange({ secret: event.target.value })}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" loading={isBusy} onClick={onSave} type="button">
          保存配置
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={isBusy}
          onClick={onTest}
          type="button"
        >
          测试连接
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={isBusy}
          onClick={onActivate}
          type="button"
        >
          激活
        </Button>
        <span className="font-mono text-xs text-muted-foreground">
          {metadata?.configured ? `•••• ${metadata.last_four}` : "未配置"}
        </span>
      </div>

      {health ? (
        <p className="text-xs text-muted-foreground">
          {health.status} · {health.latency_ms ?? "--"} ms
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-negative" role="alert">
          {error}
        </p>
      ) : null}
      {success ? (
        <p className="text-xs text-positive" role="status">
          {success}
        </p>
      ) : null}
    </section>
  );
}

function buildInitialDrafts(
  providers: ProviderConfigSummary[],
): Record<ProviderCategoryId, DraftState> {
  return Object.fromEntries(
    PROVIDER_CATEGORIES.map((category) => {
      const provider = chooseProviderForCategory(providers, category.id);
      return [
        category.id,
        {
          model: provider?.model_name ?? "",
          secret: "",
          url: provider?.base_url ?? "",
        },
      ];
    }),
  ) as Record<ProviderCategoryId, DraftState>;
}

function chooseProviderFromSelection(
  providers: ProviderConfigSummary[],
  category: ProviderCategoryId,
  selectedVersionId?: string,
): ProviderConfigSummary | null {
  if (selectedVersionId) {
    const selected = providers.find(
      (provider) => provider.version_id === selectedVersionId,
    );
    if (selected) {
      return selected;
    }
  }
  return chooseProviderForCategory(providers, category);
}

function providerSummaryFromRecord(
  record: VersionedConfigRecord,
  category: ProviderCategoryDefinition,
  detection: { providerId: string; label: string; isCustom: boolean },
): ProviderConfigSummary {
  const versionId =
    typeof record.version_id === "string"
      ? record.version_id
      : `provider-${category.id}-${globalThis.crypto.randomUUID()}`;
  const nonSensitiveConfig = record.non_sensitive_config as
    | Record<string, unknown>
    | undefined;
  return {
    base_url: (record.base_url as string | null | undefined) ?? null,
    detected_label:
      (nonSensitiveConfig?.detected_label as string | undefined) ?? detection.label,
    detected_provider:
      (nonSensitiveConfig?.detected_provider as string | undefined) ??
      detection.providerId,
    enabled: (record.enabled as boolean | undefined) ?? true,
    is_custom_provider:
      (nonSensitiveConfig?.is_custom_provider as boolean | undefined) ??
      detection.isCustom,
    lifecycle: (record.lifecycle as string | undefined) ?? "draft",
    model_name: (record.model_name as string | null | undefined) ?? null,
    provider_category:
      (nonSensitiveConfig?.provider_category as ProviderCategoryId | undefined) ??
      category.id,
    provider_name:
      (record.provider_name as string | undefined) ??
      providerNameForCategory(category, detection),
    provider_type: (record.provider_type as string | undefined) ?? category.providerType,
    secret_metadata: null,
    version_id: versionId,
  };
}
