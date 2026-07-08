"use client";

/**
 * @fileoverview Escaped evidence locator list for v0.2 detail pages.
 */

import { FileText, Globe, Link2, Megaphone, Newspaper } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EvidenceLocatorListItem } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

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
  const { language, t } = useLanguage();
  const labelSeparator = language === "zh" ? "：" : ": ";
  if (evidence.length === 0) {
    return (
      <Card>
        <CardContent className="grid place-items-center rounded-md border border-dashed border-border py-8 text-sm text-muted-foreground">
          {t("evidenceEmpty")}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card aria-labelledby="evidence-locator-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            {t("evidenceTitle")}
          </p>
          <CardTitle id="evidence-locator-title" className="mt-1">
            {t("evidenceTitle")}
          </CardTitle>
        </div>
        <span className="text-xs text-muted-foreground">
          {evidence.length} {t("evidenceCount")}
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
              <div className="grid min-w-0 flex-1 gap-2">
                <strong className="text-sm leading-snug text-foreground">
                  {item.title || item.evidence_id}
                </strong>
                {item.snippet ? (
                  <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                    {item.snippet}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>{t("evidenceLevel")} {item.source_level}</span>
                  {item.source_name ? <span>{item.source_name}</span> : null}
                </div>
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer text-accent">
                    {t("evidenceTechnical")}
                  </summary>
                  <div className="mt-1 grid gap-1 rounded-md border border-border bg-muted/40 p-2">
                    <span>{t("evidenceLocator")}{labelSeparator}{item.locator}</span>
                    <span>{t("evidenceSnapshot")}{labelSeparator}{item.snapshot_id || "--"}</span>
                    {item.pit_timestamp ? (
                      <span>{t("evidencePit")}{labelSeparator}{item.pit_timestamp}</span>
                    ) : null}
                  </div>
                </details>
              </div>
              <div className="grid shrink-0 justify-items-end gap-1.5">
                <Badge tone={sourceTone(item.source_level)}>
                  {item.source_level}
                </Badge>
                {typeof item.linked_to_security === "boolean" ? (
                  <Badge tone={item.linked_to_security ? "positive" : "caution"}>
                    {item.linked_to_security
                      ? t("evidenceLinked")
                      : t("evidenceNeedsReview")}
                  </Badge>
                ) : null}
                {item.source_url ? (
                  <a
                    className="text-xs text-accent no-underline hover:underline"
                    href={item.source_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {t("evidenceOriginal")}
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
