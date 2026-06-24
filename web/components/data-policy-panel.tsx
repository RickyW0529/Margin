"use client";

/**
 * @fileoverview Versioned rolling-window data acquisition settings.
 */

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  activateDataPolicy,
  createDataPolicy,
  triggerDataSync,
  type DataPolicyCreate,
  type DataPolicyListResponse,
  type DataPolicyVersion,
} from "@/lib/api";
import { formatDateShort } from "@/lib/utils";

type DataPolicyPanelProps = {
  initialPolicies: DataPolicyListResponse;
  createPolicy?: (request: DataPolicyCreate) => Promise<DataPolicyVersion>;
  activatePolicy?: (versionId: string) => Promise<DataPolicyVersion>;
  triggerSync?: () => Promise<{ sync_run_id: string; status: string }>;
};

/** Renders the rolling-window policy editor and explicit activation/sync actions. */
export function DataPolicyPanel({
  initialPolicies,
  createPolicy = createDataPolicy,
  activatePolicy = activateDataPolicy,
  triggerSync = () => triggerDataSync({ requested_by: "data-policy-ui" }),
}: DataPolicyPanelProps) {
  const [policies, setPolicies] = useState(initialPolicies.versions);
  const [activeVersionId, setActiveVersionId] = useState(
    initialPolicies.active_version_id,
  );
  const [months, setMonths] = useState(24);
  const [revisionDays, setRevisionDays] = useState(30);
  const [comparisonYears, setComparisonYears] = useState(1);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const activePolicy = useMemo(
    () =>
      policies.find((policy) => policy.version_id === activeVersionId) ??
      policies.find((policy) => policy.lifecycle === "active") ??
      null,
    [activeVersionId, policies],
  );
  const draftPolicies = policies.filter(
    (policy) => policy.version_id !== activePolicy?.version_id,
  );

  function validate(): boolean {
    if (months < 12 || months > 60) {
      setError("滚动数据窗口必须在 12 到 60 个月之间。");
      return false;
    }
    setError(null);
    return true;
  }

  async function handleCreate() {
    if (!validate()) {
      return;
    }
    setBusyAction("create");
    setSuccess(null);
    try {
      const created = await createPolicy({
        rolling_window_months: months,
        revision_lookback_days: revisionDays,
        financial_comparison_years: comparisonYears,
      });
      setPolicies((current) => [
        created,
        ...current.filter((item) => item.version_id !== created.version_id),
      ]);
      setSuccess("新版本已保存，激活后才会影响后续同步。");
    } catch {
      setError("保存失败，请检查管理员会话和后端数据策略服务。");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleActivate(versionId: string) {
    setBusyAction(`activate:${versionId}`);
    setError(null);
    setSuccess(null);
    try {
      const activated = await activatePolicy(versionId);
      setPolicies((current) =>
        current.map((policy) => {
          if (policy.version_id === activated.version_id) {
            return activated;
          }
          if (policy.lifecycle === "active") {
            return { ...policy, lifecycle: "deprecated" };
          }
          return policy;
        }),
      );
      setActiveVersionId(activated.version_id);
      setSuccess("数据策略已激活。后续同步将使用新的滚动窗口。");
    } catch {
      setError("激活失败，请检查版本状态和管理员会话。");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSync() {
    setBusyAction("sync");
    setError(null);
    setSuccess(null);
    try {
      const run = await triggerSync();
      setSuccess(`后台同步已创建：${run.sync_run_id}`);
    } catch {
      setError("同步任务创建失败，请检查 Provider、管理员会话和 Worker 状态。");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card className="md:col-span-2 lg:col-span-1">
        <CardHeader>
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-accent">
              Active policy
            </p>
            <CardTitle className="mt-1">当前数据窗口</CardTitle>
          </div>
          <Badge tone="positive">
            {activePolicy?.lifecycle ?? "default"}
          </Badge>
        </CardHeader>
        <CardContent className="grid gap-4">
          {activePolicy ? (
            <>
              <div className="grid gap-1 rounded-md border border-border bg-muted/40 p-4">
                <strong className="text-2xl font-semibold tracking-tight text-foreground">
                  {activePolicy.rolling_window_months} 个月
                </strong>
                <span className="text-xs text-muted-foreground">
                  {formatDateShort(activePolicy.window_start)} →{" "}
                  {formatDateShort(activePolicy.window_end)}
                </span>
              </div>
              <dl className="grid grid-cols-3 gap-2">
                <div className="grid gap-1 rounded-md border border-border bg-muted/40 p-3">
                  <dt className="text-xs text-muted-foreground">修订回抓</dt>
                  <dd className="text-sm font-semibold text-foreground">
                    {activePolicy.revision_lookback_days} 天
                  </dd>
                </div>
                <div className="grid gap-1 rounded-md border border-border bg-muted/40 p-3">
                  <dt className="text-xs text-muted-foreground">财务比较期</dt>
                  <dd className="text-sm font-semibold text-foreground">
                    {activePolicy.financial_comparison_years} 年
                  </dd>
                </div>
                <div className="grid gap-1 rounded-md border border-border bg-muted/40 p-3">
                  <dt className="text-xs text-muted-foreground">采集范围</dt>
                  <dd className="text-sm font-semibold text-foreground">
                    仅量化需求
                  </dd>
                </div>
              </dl>
              <p className="text-xs leading-relaxed text-muted-foreground">
                证券主数据、ST 状态与审计历史不受两年窗口硬删除。
              </p>
              <Button
                loading={busyAction === "sync"}
                disabled={busyAction !== null}
                onClick={handleSync}
                type="button"
              >
                {busyAction === "sync" ? "正在创建…" : "按当前策略同步"}
              </Button>
            </>
          ) : (
            <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
              暂无有效数据策略
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-accent">
              New version
            </p>
            <CardTitle className="mt-1">创建滚动窗口版本</CardTitle>
          </div>
          <span className="text-xs text-muted-foreground">12–60 months</span>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="grid gap-1.5">
            <Label>滚动数据窗口（月）</Label>
            <Input
              aria-label="滚动数据窗口（月）"
              disabled={busyAction !== null}
              max={60}
              min={12}
              type="number"
              value={months}
              onChange={(event) => setMonths(Number(event.target.value))}
            />
          </div>
          <div className="grid gap-1.5">
            <Label>修订回抓（天）</Label>
            <Input
              aria-label="修订回抓（天）"
              disabled={busyAction !== null}
              max={365}
              min={0}
              type="number"
              value={revisionDays}
              onChange={(event) => setRevisionDays(Number(event.target.value))}
            />
          </div>
          <div className="grid gap-1.5">
            <Label>财务比较期（年）</Label>
            <Input
              aria-label="财务比较期（年）"
              disabled={busyAction !== null}
              max={3}
              min={1}
              type="number"
              value={comparisonYears}
              onChange={(event) =>
                setComparisonYears(Number(event.target.value))
              }
            />
          </div>
          <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            窗口越长，行情与财务表占用越大。未被当前量化需求引用的 endpoint 不会采集。
          </div>
          <Button
            variant="secondary"
            loading={busyAction === "create"}
            disabled={busyAction !== null}
            onClick={handleCreate}
            type="button"
          >
            {busyAction === "create" ? "正在保存…" : "保存新版本"}
          </Button>
        </CardContent>
      </Card>

      <Card className="md:col-span-2">
        <CardHeader>
          <CardTitle>待激活与历史版本</CardTitle>
          <span className="text-xs text-muted-foreground">
            {draftPolicies.length} versions
          </span>
        </CardHeader>
        <CardContent className="grid gap-2">
          {draftPolicies.length === 0 ? (
            <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
              暂无其他版本
            </div>
          ) : (
            draftPolicies.map((policy) => (
              <div
                key={policy.version_id}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2.5"
              >
                <div className="grid min-w-0 gap-0.5">
                  <strong className="text-sm text-foreground">
                    {policy.rolling_window_months} 个月
                  </strong>
                  <span className="text-xs text-muted-foreground">
                    {policy.lifecycle} · {formatDateShort(policy.window_start)}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  loading={busyAction === `activate:${policy.version_id}`}
                  disabled={
                    busyAction !== null || policy.lifecycle === "deprecated"
                  }
                  onClick={() => handleActivate(policy.version_id)}
                  type="button"
                >
                  {busyAction === `activate:${policy.version_id}`
                    ? "正在激活…"
                    : `激活 ${policy.rolling_window_months} 个月版本`}
                </Button>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {error ? (
        <p className="text-xs text-negative md:col-span-2" role="alert">
          {error}
        </p>
      ) : null}
      {success ? (
        <p className="text-xs text-positive md:col-span-2" role="status">
          {success}
        </p>
      ) : null}
    </div>
  );
}
