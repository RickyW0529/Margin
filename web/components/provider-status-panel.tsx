/**
 * @fileoverview Panel component that displays the operational status of data
 * and model providers with localized status badges.
 */

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { ProviderStatus } from "@/lib/api";

type ProviderStatusPanelProps = {
  providers: ProviderStatus[];
  title?: string;
};

function statusTone(status: string): BadgeProps["tone"] {
  const normalized = status.toLowerCase();
  if (["healthy", "ready", "ok"].includes(normalized)) {
    return "positive";
  }
  if (["degraded", "warning", "unavailable"].includes(normalized)) {
    return "caution";
  }
  if (["failed", "error", "unhealthy"].includes(normalized)) {
    return "negative";
  }
  return "muted";
}

/** Renders a list of provider statuses with localized status badges. */
export function ProviderStatusPanel({
  providers,
  title = "Provider 状态",
}: ProviderStatusPanelProps) {
  const healthyCount = providers.filter((provider) =>
    ["healthy", "ready", "ok"].includes(provider.status.toLowerCase()),
  ).length;
  const blockerCount = providers.length - healthyCount;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {healthyCount} healthy / {blockerCount} blocker
        </span>
      </CardHeader>
      <CardContent className="grid gap-2">
        {providers.length === 0 ? (
          <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
            暂无 Provider 状态
          </div>
        ) : (
          providers.map((provider) => (
            <div
              key={provider.provider}
              className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2.5"
            >
              <div className="grid min-w-0 gap-0.5">
                <strong className="truncate text-sm text-foreground">
                  {provider.provider}
                </strong>
                <span className="truncate text-xs text-muted-foreground">
                  {provider.message}
                </span>
              </div>
              <Badge tone={statusTone(provider.status)}>{provider.status}</Badge>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
