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

  async function handleActivate(versionId: string) {
    setBusy(versionId);
    setError(null);
    setSuccess(null);
    try {
      await activateVersionedConfig(kind, versionId);
      setSuccess(`${versionId} 已激活。`);
    } catch {
      setError("激活失败，请检查管理员会话与版本状态。");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {records.length} versions
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
            return (
              <div
                key={id}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2.5"
              >
                <div className="grid min-w-0 gap-0.5">
                  <strong className="truncate text-sm text-foreground">
                    {id}
                  </strong>
                  <span className="text-xs text-muted-foreground">
                    {lifecycle} · {String(record.owner_id ?? "local-admin")}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={lifecycleTone(lifecycle)}>{lifecycle}</Badge>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy !== null || lifecycle === "active"}
                    loading={busy === id}
                    onClick={() => handleActivate(id)}
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
