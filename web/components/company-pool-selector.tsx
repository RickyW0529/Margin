"use client";

/**
 * @fileoverview User-facing company-pool selector for research scope settings.
 */

import { CheckCircle2, Clock3, Database, Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  activateVersionedConfig,
  type VersionedConfigKind,
  type VersionedConfigRecord,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type CompanyPoolOption = {
  code: "CSI500" | "ALL_A" | "CSI300";
  label: string;
  description: string;
  indexCode: string | null;
};

type CompanyPoolSelectorProps = {
  universes: VersionedConfigRecord[];
  scopes: VersionedConfigRecord[];
  activateConfig?: (
    kind: VersionedConfigKind,
    versionId: string,
  ) => Promise<VersionedConfigRecord>;
};

const DEFAULT_POOLS: CompanyPoolOption[] = [
  {
    code: "CSI500",
    description: "中盘指数成分股，适合发现成长与估值错配机会。",
    indexCode: "000905.SH",
    label: "中证500",
  },
  {
    code: "ALL_A",
    description: "当前全市场候选池，排除 ST、退市与未满足基础条件的公司。",
    indexCode: null,
    label: "全 A",
  },
  {
    code: "CSI300",
    description: "大盘核心指数成分股，适合偏稳健的研究范围。",
    indexCode: "000300.SH",
    label: "沪深300",
  },
];

/** Renders the supported company pools and switches the active research scope. */
export function CompanyPoolSelector({
  universes,
  scopes,
  activateConfig = activateVersionedConfig,
}: CompanyPoolSelectorProps) {
  const router = useRouter();
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const activeUniverseId = stringField(
    scopes.find((scope) => stringField(scope, "lifecycle") === "active"),
    "universe_version_id",
  );
  const universeByCode = useMemo(() => {
    return new Map(
      universes
        .map((universe) => [stringField(universe, "universe_code"), universe] as const)
        .filter(([code]) => code !== null),
    );
  }, [universes]);

  async function handleSwitch(option: CompanyPoolOption, versionId: string) {
    setBusyCode(option.code);
    setError(null);
    setSuccess(null);
    try {
      await activateConfig("universe-configs", versionId);
      setSuccess(`${option.label} 已设为当前公司池，下一次刷新将按它重新计算。`);
      router.refresh();
    } catch (caught) {
      setError(`切换失败：${messageFromError(caught)}`);
    } finally {
      setBusyCode(null);
    }
  }

  return (
    <Card>
      <CardHeader className="items-start">
        <span className="grid gap-1">
          <CardTitle>公司池</CardTitle>
          <CardDescription>
            当前默认支持中证500、全 A、沪深300；后续会开放自定义公司池。
          </CardDescription>
        </span>
        <Badge tone="accent">影响今日刷新</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-3">
          {DEFAULT_POOLS.map((option) => {
            const universe = universeByCode.get(option.code);
            const versionId = stringField(universe, "version_id");
            const lifecycle = stringField(universe, "lifecycle") ?? "not_configured";
            const count = memberCount(universe);
            const isConfigured = versionId !== null && count > 0;
            const isCurrent = isConfigured && versionId === activeUniverseId;
            const isBusy = busyCode === option.code;
            const disabled = !isConfigured || isCurrent || busyCode !== null;
            return (
              <article
                className={cn(
                  "grid min-h-[220px] gap-4 rounded-lg border bg-muted/20 p-4 transition-colors",
                  isCurrent
                    ? "border-positive/40 bg-positive-soft/40"
                    : "border-border hover:bg-muted/40",
                )}
                data-testid={`company-pool-${option.code}`}
                key={option.code}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-md bg-card text-accent">
                    {isCurrent ? (
                      <CheckCircle2 className="size-5 text-positive" />
                    ) : isConfigured ? (
                      <Database className="size-5" />
                    ) : (
                      <Clock3 className="size-5 text-muted-foreground" />
                    )}
                  </span>
                  <PoolStatusBadge
                    isConfigured={isConfigured}
                    isCurrent={isCurrent}
                    lifecycle={lifecycle}
                  />
                </div>
                <div className="grid gap-1.5">
                  <h3 className="text-base font-semibold text-foreground">
                    {option.label}
                  </h3>
                  <p className="min-h-12 text-sm leading-6 text-muted-foreground">
                    {option.description}
                  </p>
                </div>
                <div className="grid gap-1 text-xs text-muted-foreground">
                  <span>
                    成员数：
                    <strong className="text-foreground">
                      {isConfigured ? `${count} 只` : "等待数据同步"}
                    </strong>
                  </span>
                  <span>
                    规则：
                    {option.indexCode ?? "数据层全市场公司池"}
                  </span>
                </div>
                <Button
                  aria-label={`切换到${option.label}`}
                  className="mt-auto"
                  disabled={disabled}
                  loading={isBusy}
                  onClick={() => {
                    if (versionId !== null) {
                      void handleSwitch(option, versionId);
                    }
                  }}
                  type="button"
                  variant={isCurrent ? "secondary" : "primary"}
                >
                  {isCurrent ? "当前使用" : "切换"}
                </Button>
              </article>
            );
          })}
          <article className="grid min-h-[220px] gap-4 rounded-lg border border-dashed border-border bg-muted/10 p-4">
            <span className="grid size-10 place-items-center rounded-md bg-card text-muted-foreground">
              <Lock className="size-5" />
            </span>
            <div className="grid gap-1.5">
              <h3 className="text-base font-semibold text-foreground">
                自定义公司池
              </h3>
              <p className="text-sm leading-6 text-muted-foreground">
                后续支持上传名单、保存筛选规则，并生成可审计的公司池版本。
              </p>
            </div>
            <Button className="mt-auto" disabled type="button" variant="secondary">
              后续开放
            </Button>
          </article>
        </div>
        {error ? (
          <p className="text-sm text-negative" role="alert">
            {error}
          </p>
        ) : null}
        {success ? (
          <p className="text-sm text-positive" role="status">
            {success}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function PoolStatusBadge({
  isConfigured,
  isCurrent,
  lifecycle,
}: {
  isConfigured: boolean;
  isCurrent: boolean;
  lifecycle: string;
}) {
  if (isCurrent) {
    return <Badge tone="positive">当前使用</Badge>;
  }
  if (!isConfigured) {
    return <Badge tone="caution">等待数据同步</Badge>;
  }
  if (lifecycle === "active" || lifecycle === "draft" || lifecycle === "review") {
    return <Badge tone="neutral">可切换</Badge>;
  }
  return <Badge tone="muted">可切换</Badge>;
}

function stringField(
  record: Record<string, unknown> | undefined,
  key: string,
): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function memberCount(record: Record<string, unknown> | undefined): number {
  const members = record?.member_security_ids;
  return Array.isArray(members) ? members.length : 0;
}

function messageFromError(caught: unknown): string {
  if (!(caught instanceof Error) || !caught.message) {
    return "请检查公司池版本状态。";
  }
  return caught.message;
}
