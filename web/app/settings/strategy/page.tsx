/**
 * @fileoverview Strategy settings page.
 */

import { ConfigVersionList } from "@/components/config-version-list";
import { QuantStrategyCustomizer } from "@/components/quant-strategy-customizer";
import {
  fetchQuantFeatureSets,
  fetchQuantStrategyDefaults,
  fetchQuantStrategies,
  fetchStylePrompts,
} from "@/lib/api";

export const dynamic = "force-dynamic";

/** Renders active quant strategy, feature-set, and style-prompt versions. */
export default async function StrategySettingsPage() {
  const [strategies, featureSets, prompts] = await Promise.allSettled([
    fetchQuantStrategies(),
    fetchQuantFeatureSets(),
    fetchStylePrompts(),
  ]);
  const defaults = await fetchQuantStrategyDefaults().catch(() => null);

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-10 py-9">
      <header>
        <p className="text-xs font-medium uppercase tracking-wider text-accent">
          Settings
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
          Strategy 设置
        </h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          量化策略、特征集与风格 Prompt 的修改均生成新版本，激活经审计且不可回写。
        </p>
      </header>
      {defaults ? (
        <QuantStrategyCustomizer defaults={defaults} />
      ) : (
        <div
          className="rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          默认量化策略暂时不可用，请检查后端策略配置服务。
        </div>
      )}
      <div className="grid gap-6 md:grid-cols-2">
        <ConfigVersionList
          title="量化策略"
          kind="quant-strategies"
          records={fulfilled(strategies)}
        />
        <ConfigVersionList
          title="量化特征集"
          kind="quant-feature-sets"
          records={fulfilled(featureSets)}
        />
      </div>
      <ConfigVersionList
        title="风格 Prompt"
        kind="style-prompts"
        records={fulfilled(prompts)}
      />
    </main>
  );
}

function fulfilled<T>(result: PromiseSettledResult<T[]>): T[] {
  return result.status === "fulfilled" ? result.value : [];
}
