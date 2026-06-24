/**
 * @fileoverview Rolling-window data acquisition policy settings page.
 */

import { DataPolicyPanel } from "@/components/data-policy-panel";
import {
  fetchDataPolicies,
  type DataPolicyListResponse,
} from "@/lib/api";

export const dynamic = "force-dynamic";

/** Renders the versioned data-window control plane. */
export default async function DataPolicySettingsPage() {
  let policies: DataPolicyListResponse = {
    active_version_id: "",
    versions: [],
  };
  let error: string | null = null;

  try {
    policies = await fetchDataPolicies();
  } catch {
    error = "数据策略暂时不可用，请检查 API 与数据库迁移。";
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-10 py-9">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Settings · Data
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            滚动数据策略
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            只采集当前量化明确需要的数据。默认最近两年，并按日滚动更新。
          </p>
        </div>
        <div className="flex gap-2">
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            默认 24 个月
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            服务端范围 12–60 个月
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
      ) : (
        <DataPolicyPanel initialPolicies={policies} />
      )}
    </main>
  );
}
