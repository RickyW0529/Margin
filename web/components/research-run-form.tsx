"use client";

/**
 * @fileoverview Form component for launching a v0.2 valuation refresh.
 * On success it navigates to the run detail page so the user can watch progress.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  startValuationDiscoveryRefresh,
  type ValuationDiscoveryRefreshCreate,
  type ValuationDiscoveryRefreshStart,
} from "@/lib/api";

type ResearchRunFormProps = {
  startRefresh?: (
    refresh: ValuationDiscoveryRefreshCreate,
  ) => Promise<ValuationDiscoveryRefreshStart>;
};

/** Renders a scope-driven valuation-discovery refresh form. */
export function ResearchRunForm({
  startRefresh = startValuationDiscoveryRefresh,
}: ResearchRunFormProps = {}) {
  const router = useRouter();
  const [scopeVersionId, setScopeVersionId] = useState("scope-current");
  const [decisionAt, setDecisionAt] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await startRefresh({
        scope_version_id: scopeVersionId.trim(),
        decision_at: decisionAt
          ? new Date(decisionAt).toISOString()
          : new Date().toISOString(),
      });
      router.push(`/research/runs/${result.run_id}`);
    } catch (caught) {
      setError(refreshErrorMessage(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card aria-labelledby="research-run-form-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Valuation Discovery
          </p>
          <CardTitle id="research-run-form-title" className="mt-1">
            启动估值发现刷新
          </CardTitle>
        </div>
        <span className="text-xs text-muted-foreground">
          POST /api/v1/valuation-discovery/refreshes
        </span>
      </CardHeader>
      <CardContent>
        <form className="grid gap-3" onSubmit={submit}>
          <div className="grid gap-1.5">
            <Label>研究作用域版本</Label>
            <Input
              aria-label="研究作用域版本"
              name="scope_version_id"
              required
              value={scopeVersionId}
              onChange={(event) => setScopeVersionId(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label>决策时间</Label>
            <Input
              aria-label="决策时间"
              name="decision_at"
              type="datetime-local"
              value={decisionAt}
              onChange={(event) => setDecisionAt(event.target.value)}
            />
          </div>
          <p className="text-xs leading-relaxed text-muted-foreground">
            公司池、指标视图、量化策略、Prompt 和工具权限均来自 active scope。这里不会按手工 symbol 跑旧研究工作流。
          </p>
          {error ? (
            <div
              className="rounded-md border border-negative-soft bg-negative-soft px-3 py-2 text-xs text-negative"
              role="alert"
            >
              {error}
            </div>
          ) : null}
          <Button type="submit" loading={pending}>
            启动估值发现
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function refreshErrorMessage(caught: unknown): string {
  if (!(caught instanceof Error)) {
    return "启动失败，请检查管理员会话、active scope、Provider 和后端任务队列。";
  }
  if (caught.message.includes("Local admin session")) {
    return "请先在右上角解锁管理员模式。";
  }
  if (
    caught.message.includes("service_not_configured") &&
    caught.message.includes("tavily")
  ) {
    return "Tavily Provider 未激活或不可用，先到 Provider 密钥配置页处理 WebSearch 状态。";
  }
  if (caught.message.includes("service_not_configured")) {
    return "估值发现依赖的 Provider 或 active scope 未配置，先检查 Provider 与 Scope 设置。";
  }
  return "启动失败，请检查管理员会话、active scope、Provider 和后端任务队列。";
}
