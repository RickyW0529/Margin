/**
 * @fileoverview Escaped evidence locator list for v0.2 detail pages.
 */

import { FileText, Globe, Link2, Megaphone, Newspaper } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EvidenceLocatorListItem } from "@/lib/api";

type EvidenceLocatorListProps = {
  evidence: EvidenceLocatorListItem[];
};

const SOURCE_ICON: Record<string, React.ElementType> = {
  official: Megaphone,
  primary: FileText,
  secondary: Newspaper,
  tertiary: Globe,
};

function sourceTone(level: string): "positive" | "caution" | "muted" {
  if (level === "official" || level === "primary" || level === "L1") {
    return "positive";
  }
  if (level === "secondary" || level === "L2") {
    return "caution";
  }
  return "muted";
}

/** Renders evidence locator rows without interpreting external text as HTML. */
export function EvidenceLocatorList({ evidence }: EvidenceLocatorListProps) {
  if (evidence.length === 0) {
    return (
      <Card>
        <CardContent className="grid place-items-center rounded-md border border-dashed border-border py-8 text-sm text-muted-foreground">
          暂无 v0.2 证据定位
        </CardContent>
      </Card>
    );
  }

  return (
    <Card aria-labelledby="evidence-locator-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Evidence package
          </p>
          <CardTitle id="evidence-locator-title" className="mt-1">
            证据定位
          </CardTitle>
        </div>
        <span className="text-xs text-muted-foreground">
          {evidence.length} locators
        </span>
      </CardHeader>
      <CardContent className="grid divide-y divide-border">
        {evidence.map((item) => {
          const Icon = SOURCE_ICON[item.source_level] ?? Link2;
          return (
            <div
              key={item.evidence_id}
              className="flex items-start gap-3 py-3 first:pt-0 last:pb-0"
            >
              <div className="grid size-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
                <Icon className="size-3.5" />
              </div>
              <div className="grid min-w-0 flex-1 gap-1">
                <strong className="text-sm leading-snug text-foreground">
                  {item.title || item.evidence_id}
                </strong>
                <span className="text-xs text-muted-foreground">
                  {item.locator}
                </span>
                {item.snippet ? (
                  <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                    {item.snippet}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>snapshot</span>
                  <span>{item.snapshot_id || "--"}</span>
                  {item.source_name ? <span>{item.source_name}</span> : null}
                  {item.pit_timestamp ? (
                    <span>PIT {item.pit_timestamp}</span>
                  ) : null}
                </div>
              </div>
              <div className="grid shrink-0 justify-items-end gap-1.5">
                <Badge tone={sourceTone(item.source_level)}>
                  {item.source_level}
                </Badge>
                {typeof item.linked_to_security === "boolean" ? (
                  <Badge tone={item.linked_to_security ? "positive" : "caution"}>
                    {item.linked_to_security ? "已关联本股票" : "需复核关联"}
                  </Badge>
                ) : null}
                {item.source_url ? (
                  <a
                    className="text-xs text-accent no-underline hover:underline"
                    href={item.source_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    原文
                  </a>
                ) : null}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
