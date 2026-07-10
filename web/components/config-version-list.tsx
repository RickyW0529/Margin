"use client";

/**
 * @fileoverview Generic versioned-config list with append-only activation.
 */

import { useState } from "react";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  activateVersionedConfig,
  type VersionedConfigKind,
  type VersionedConfigRecord,
} from "@/lib/api";

type ConfigVersionListProps = {
  title: string;
  kind: VersionedConfigKind;
  records: VersionedConfigRecord[];
  empty?: string;
};

function lifecycleTone(lifecycle: string): BadgeProps["tone"] {
  if (lifecycle === "active") {
    return "positive";
  }
  if (lifecycle === "deprecated" || lifecycle === "archived") {
    return "muted";
  }
  if (lifecycle === "draft") {
    return "caution";
  }
  return "neutral";
}

function lifecycleLabel(lifecycle: string): string {
  const labels: Record<string, string> = {
    active: "已激活",
    archived: "已归档",
    deprecated: "已停用",
    draft: "草稿",
    review: "待审核",
    unknown: "未知",
  };
  return labels[lifecycle] ?? lifecycle;
}

function versionDisplayName(
  record: VersionedConfigRecord,
  index: number,
): string {
  for (const key of [
    "display_name",
    "name",
    "label",
    "strategy_family",
    "title",
  ] as const) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  const createdAt = record.created_at ?? record.activated_at;
  if (typeof createdAt === "string" && createdAt) {
    return `版本 ${index + 1} · ${createdAt.slice(0, 10)}`;
  }
  return `版本 ${index + 1}`;
}

/** Renders versioned config records with explicit activation controls. */
export function ConfigVersionList({
  title,
  kind,
  records,
  empty = "暂无版本",
}: ConfigVersionListProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleActivate(versionId: string, displayName: string) {
    setBusy(versionId);
    setError(null);
    setSuccess(null);
    try {
      await activateVersionedConfig(kind, versionId);
      setSuccess(`「${displayName}」已激活。`);
    } catch (caught) {
      setError(`激活失败：${messageFromError(caught)}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {records.length} 个版本
        </span>
      </CardHeader>
      <CardContent className="grid gap-2">
        {records.length === 0 ? (
          <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-center text-sm text-muted-foreground">
            {empty}
          </div>
        ) : (
          records.map((record, index) => {
            const id = String(record.version_id ?? `version-${index + 1}`);
            const lifecycle = String(record.lifecycle ?? "unknown");
            const displayName = versionDisplayName(record, index);
            return (
              <div
                key={id}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2.5"
              >
                <div className="grid min-w-0 gap-0.5">
                  <strong className="truncate text-sm text-foreground">
                    {displayName}
                  </strong>
                  <span className="text-xs text-muted-foreground">
                    {lifecycleLabel(lifecycle)}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={lifecycleTone(lifecycle)}>
                    {lifecycleLabel(lifecycle)}
                  </Badge>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy !== null || lifecycle === "active"}
                    loading={busy === id}
                    onClick={() => handleActivate(id, displayName)}
                    type="button"
                  >
                    激活
                  </Button>
                </div>
              </div>
            );
          })
        )}
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
      </CardContent>
    </Card>
  );
}

function messageFromError(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "请稍后重试";
}
