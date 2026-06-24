"use client";

/**
 * @fileoverview Strategy detail client component.
 *
 * Renders the strategy profile, its versions and lifecycle controls
 * (validate / backtest / paper-trade / activate / archive) plus a prompt
 * preview.
 */

import { useCallback, useState } from "react";
import Link from "next/link";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  activateStrategyVersion,
  archiveStrategy,
  backtestStrategyVersion,
  fetchStrategyDetail,
  fetchStrategyPrompt,
  paperTradeStrategyVersion,
  validateStrategyVersion,
} from "@/lib/api";
import { formatDateShort } from "@/lib/utils";

type StrategyVersionLike = {
  version_id?: string;
  name?: string;
  state?: string;
  description?: string;
  created_at?: string;
};

type StrategyProfileLike = Record<string, unknown> & {
  strategy_id?: string;
  owner_id?: string;
  name?: string;
  active_version_id?: string;
  versions?: StrategyVersionLike[];
};

type StrategyDetailClientProps = {
  strategyId: string;
  initialProfile: StrategyProfileLike | null;
  initialError: string | null;
};

const LIFECYCLE_ORDER: Record<string, string> = {
  draft: "validate",
  validating: "validate",
  invalid: "validate",
  backtesting: "backtest",
  paper_trading: "paper-trade",
  active: "active",
};

function stateTone(state: string | undefined): BadgeProps["tone"] {
  if (state === "active") {
    return "positive";
  }
  if (state === "archived" || state === "invalid" || state === "suspended") {
    return "negative";
  }
  if (state === "validating" || state === "backtesting" || state === "paper_trading") {
    return "caution";
  }
  return "muted";
}

export function StrategyDetailClient({
  strategyId,
  initialProfile,
  initialError,
}: StrategyDetailClientProps) {
  const [profile, setProfile] = useState<StrategyProfileLike | null>(
    initialProfile,
  );
  const [error, setError] = useState<string | null>(initialError);
  const [pending, setPending] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const next = await fetchStrategyDetail(strategyId);
      setProfile(next as StrategyProfileLike);
      setError(null);
    } catch {
      setError("策略刷新失败");
    }
  }, [strategyId]);

  async function runAction(key: string, fn: () => Promise<unknown>) {
    setPending(key);
    try {
      await fn();
      await reload();
    } catch {
      setError(`${key} 失败，请确认管理员会话与策略状态。`);
    } finally {
      setPending(null);
    }
  }

  async function showPrompt(versionId: string) {
    setPromptError(null);
    try {
      const response = await fetchStrategyPrompt(strategyId, versionId);
      setPrompt(response.prompt);
    } catch {
      setPromptError("Prompt 加载失败");
    }
  }

  const versions = profile?.versions ?? [];

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-10 py-9">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Strategy
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            {profile?.name ?? strategyId}
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {profile?.strategy_id ?? ""}
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            owner {String(profile?.owner_id ?? "")}
          </span>
          <Button asChild variant="secondary" size="sm">
            <Link href="/strategies">返回列表</Link>
          </Button>
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

      <Card>
        <CardHeader>
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-accent">
              Versions
            </p>
            <CardTitle className="mt-1">版本生命周期</CardTitle>
          </div>
          <span className="text-xs text-muted-foreground">
            active {String(profile?.active_version_id ?? "--")}
          </span>
        </CardHeader>
        <CardContent className="grid gap-3">
          {versions.length === 0 ? (
            <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
              暂无版本
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[760px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-left">
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      version_id
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      名称
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      状态
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      创建
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      Prompt
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((version) => {
                    const next =
                      LIFECYCLE_ORDER[version.state ?? ""] ?? "done";
                    return (
                      <tr
                        key={String(version.version_id)}
                        className="border-b border-border transition-colors last:border-b-0 hover:bg-muted/30"
                      >
                        <td className="px-3 py-3 font-mono text-xs text-foreground">
                          {version.version_id}
                        </td>
                        <td className="px-3 py-3 text-foreground">
                          {version.name}
                        </td>
                        <td className="px-3 py-3">
                          <Badge tone={stateTone(version.state)}>
                            {version.state}
                          </Badge>
                        </td>
                        <td className="px-3 py-3 text-xs text-muted-foreground">
                          {formatDateShort(version.created_at)}
                        </td>
                        <td className="px-3 py-3">
                          <button
                            type="button"
                            className="text-xs font-medium text-accent hover:underline"
                            onClick={() =>
                              void showPrompt(String(version.version_id))
                            }
                          >
                            查看
                          </button>
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            {next === "validate" ? (
                              <Button
                                size="sm"
                                loading={pending === "validate"}
                                onClick={() =>
                                  void runAction("validate", () =>
                                    validateStrategyVersion(
                                      strategyId,
                                      String(version.version_id),
                                    ),
                                  )
                                }
                                type="button"
                              >
                                校验
                              </Button>
                            ) : null}
                            {next === "backtest" ? (
                              <Button
                                size="sm"
                                loading={pending === "backtest"}
                                onClick={() =>
                                  void runAction("backtest", () =>
                                    backtestStrategyVersion(
                                      strategyId,
                                      String(version.version_id),
                                    ),
                                  )
                                }
                                type="button"
                              >
                                回测
                              </Button>
                            ) : null}
                            {next === "paper-trade" ? (
                              <Button
                                size="sm"
                                loading={pending === "paper-trade"}
                                onClick={() =>
                                  void runAction("paper-trade", () =>
                                    paperTradeStrategyVersion(
                                      strategyId,
                                      String(version.version_id),
                                    ),
                                  )
                                }
                                type="button"
                              >
                                纸面
                              </Button>
                            ) : null}
                            {next === "active" ? null : (
                              <Button
                                size="sm"
                                variant="secondary"
                                loading={pending === "activate"}
                                onClick={() =>
                                  void runAction("activate", () =>
                                    activateStrategyVersion(
                                      strategyId,
                                      String(version.version_id),
                                    ),
                                  )
                                }
                                type="button"
                              >
                                激活
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-accent">
              Prompt preview
            </p>
            <CardTitle className="mt-1">合并 Prompt</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3">
          {promptError ? (
            <p className="text-xs text-negative" role="alert">
              {promptError}
            </p>
          ) : null}
          {prompt ? (
            <pre className="max-h-72 overflow-auto rounded-md border border-border bg-foreground p-4 text-xs leading-relaxed text-background">
              {prompt}
            </pre>
          ) : (
            <p className="text-xs text-muted-foreground">
              点击某版本的「查看」预览合并后的 Prompt。
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-accent">
              Danger zone
            </p>
            <CardTitle className="mt-1">归档策略</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <Button
            variant="secondary"
            loading={pending === "archive"}
            onClick={() =>
              void runAction("archive", () => archiveStrategy(strategyId))
            }
            type="button"
          >
            归档当前激活版本
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
