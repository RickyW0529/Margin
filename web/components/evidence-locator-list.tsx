"use client";

/**
 * @fileoverview Escaped evidence locator list for v0.2 detail pages.
 */

import { BookOpenText, ExternalLink, FileText, Globe, Link2, Megaphone, Newspaper } from "lucide-react";
import { useState } from "react";

import { EvidenceReader } from "@/components/evidence-reader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EvidenceLocatorListItem } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { safeExternalHref } from "@/lib/utils";

type EvidenceLocatorListProps = {
  evidence: EvidenceLocatorListItem[];
};

type ActiveEvidence = {
  detailUrl: string | null;
  evidenceId: string;
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

function sourceLevelLabel(level: string, language: "en" | "zh"): string {
  const labels: Record<string, Record<"en" | "zh", string>> = {
    official: { en: "Official", zh: "官方" },
    primary: { en: "Primary", zh: "一级" },
    secondary: { en: "Secondary", zh: "二级" },
    tertiary: { en: "Tertiary", zh: "三级" },
    L1: { en: "L1", zh: "L1" },
    L2: { en: "L2", zh: "L2" },
    L3: { en: "L3", zh: "L3" },
    L4: { en: "L4", zh: "L4" },
  };
  return labels[level]?.[language] ?? level;
}

/** Renders evidence rows without exposing internal locator plumbing. */
export function EvidenceLocatorList({ evidence }: EvidenceLocatorListProps) {
  const { language, t } = useLanguage();
  const [activeEvidence, setActiveEvidence] = useState<ActiveEvidence | null>(null);
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
    <>
      <Card aria-labelledby="evidence-locator-title">
      <CardHeader>
        <CardTitle id="evidence-locator-title">{t("evidenceTitle")}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {evidence.length} {t("evidenceCount")}
        </span>
      </CardHeader>
      <CardContent className="grid divide-y divide-border">
        {evidence.map((item) => {
          const Icon = SOURCE_ICON[item.source_level] ?? Link2;
          const sourceHref = safeExternalHref(item.source_url);
          const openable =
            item.source_kind !== "websearch" &&
            (!item.detail_url || item.detail_url.startsWith("/api/v1/evidence/"));
          return (
            <div
              key={item.evidence_id}
              className="flex items-start gap-3 py-3 first:pt-0 last:pb-0"
            >
              <div className="grid size-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
                <Icon className="size-3.5" />
              </div>
              <div className="grid min-w-0 flex-1 gap-1.5">
                {openable ? (
                  <button
                    className="inline-flex min-h-11 items-center gap-2 justify-self-start text-left text-sm font-semibold leading-snug text-foreground transition-colors hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() =>
                      setActiveEvidence({
                        detailUrl: item.detail_url ?? null,
                        evidenceId: item.evidence_id,
                      })
                    }
                    type="button"
                  >
                    <BookOpenText className="size-4 shrink-0 text-accent" />
                    {item.title || item.evidence_id}
                  </button>
                ) : (
                  <p className="py-2 text-sm font-semibold leading-snug text-foreground">
                    {item.title || item.evidence_id}
                  </p>
                )}
                {item.snippet ? (
                  <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                    {item.snippet}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {item.source_name ? <span>{item.source_name}</span> : null}
                  {sourceHref ? (
                    <a
                      className="text-accent no-underline hover:underline"
                      href={sourceHref}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {t("evidenceOriginal")}
                      <ExternalLink className="ml-1 inline size-3" />
                    </a>
                  ) : null}
                </div>
              </div>
              <div className="grid shrink-0 justify-items-end gap-1.5">
                <Badge tone={sourceTone(item.source_level)}>
                  {sourceLevelLabel(item.source_level, language)}
                </Badge>
                {typeof item.linked_to_security === "boolean" ? (
                  <Badge tone={item.linked_to_security ? "positive" : "caution"}>
                    {item.linked_to_security
                      ? t("evidenceLinked")
                      : t("evidenceNeedsReview")}
                  </Badge>
                ) : null}
              </div>
            </div>
          );
        })}
      </CardContent>
      </Card>
      <EvidenceReader
        detailUrl={activeEvidence?.detailUrl}
        evidenceId={activeEvidence?.evidenceId ?? null}
        onOpenChange={(open) => {
          if (!open) {
            setActiveEvidence(null);
          }
        }}
        open={activeEvidence !== null}
      />
    </>
  );
}
