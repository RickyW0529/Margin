"use client";

/**
 * @fileoverview In-app canonical evidence reader with cited-range highlights.
 */

import { ExternalLink, FileText, Highlighter, Landmark, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { MarkdownContent } from "@/components/markdown-content";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  fetchEvidenceDetail,
  type EvidenceDetail,
  type EvidenceHighlight,
} from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { safeExternalHref } from "@/lib/utils";

type EvidenceReaderProps = {
  detailUrl?: string | null;
  evidenceId: string | null;
  fetchDetail?: (
    evidenceId: string,
    detailUrl?: string | null,
  ) => Promise<EvidenceDetail>;
  onOpenChange: (open: boolean) => void;
  open: boolean;
};

/** Display the complete canonical source and its exact cited excerpts. */
export function EvidenceReader({
  detailUrl,
  evidenceId,
  fetchDetail = fetchEvidenceDetail,
  onOpenChange,
  open,
}: EvidenceReaderProps) {
  const { language } = useLanguage();
  const [loadState, setLoadState] = useState<{
    detail: EvidenceDetail | null;
    error: boolean;
    evidenceId: string | null;
  }>({ detail: null, error: false, evidenceId: null });
  const detail = loadState.evidenceId === evidenceId ? loadState.detail : null;
  const error = loadState.evidenceId === evidenceId && loadState.error;
  const loading = Boolean(open && evidenceId && !detail && !error);

  useEffect(() => {
    if (!open || !evidenceId) {
      return () => undefined;
    }
    let cancelled = false;
    void fetchDetail(evidenceId, detailUrl)
      .then((nextDetail) => {
        if (!cancelled) {
          setLoadState({ detail: nextDetail, error: false, evidenceId });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadState({ detail: null, error: true, evidenceId });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [detailUrl, evidenceId, fetchDetail, open]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="max-w-[min(94vw,58rem)]" side="right">
        <SheetHeader className="px-6 py-5 md:px-8">
          <div className="flex flex-wrap items-center gap-2 pr-10">
            <Badge tone={detail?.source_kind === "document" ? "positive" : "accent"}>
              {sourceKindLabel(detail?.source_kind, language)}
            </Badge>
            {detail?.source_level ? <Badge tone="muted">{detail.source_level}</Badge> : null}
          </div>
          <SheetTitle className="mt-3 text-lg leading-snug">
            {detail?.title ?? (language === "zh" ? "证据原文" : "Evidence source")}
          </SheetTitle>
          <SheetDescription>
            {language === "zh"
              ? "完整规范化原文与本次结论实际引用的位置"
              : "Canonical full text and the exact passages used by this conclusion"}
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="bg-background/55 p-0">
          {loading ? (
            <div className="grid min-h-64 place-items-center text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-2">
                <LoaderCircle className="size-4 animate-spin" />
                {language === "zh" ? "正在读取完整证据" : "Loading full evidence"}
              </span>
            </div>
          ) : error ? (
            <div className="m-6 rounded-2xl border border-negative/20 bg-negative-soft p-5 text-sm text-negative md:m-8">
              {language === "zh"
                ? "完整证据暂时无法读取，请稍后重试。"
                : "The full evidence could not be loaded. Try again later."}
            </div>
          ) : detail ? (
            <div className="mx-auto grid max-w-[52rem] gap-6 px-5 py-6 md:px-8 md:py-8">
              <EvidenceMetadata detail={detail} language={language} />
              <article className="rounded-2xl border border-border/80 bg-card px-5 py-6 shadow-xs md:px-8 md:py-8">
                <div className="mb-6 flex items-center gap-2 border-b border-border/70 pb-4 text-xs font-semibold tracking-[0.12em] text-muted-foreground uppercase">
                  {detail.source_kind === "warehouse_fact" ? (
                    <Landmark className="size-4" />
                  ) : (
                    <FileText className="size-4" />
                  )}
                  {language === "zh" ? "完整原文" : "Full text"}
                </div>
                <MarkdownContent className="evidence-document" content={detail.markdown} />
              </article>
              <HighlightedEvidence detail={detail} language={language} />
            </div>
          ) : null}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

function sourceKindLabel(
  sourceKind: EvidenceDetail["source_kind"] | undefined,
  language: "zh" | "en",
): string {
  if (sourceKind === "warehouse_fact") {
    return language === "zh" ? "数据仓库" : "Warehouse";
  }
  if (sourceKind === "quant_result") {
    return language === "zh" ? "量化分析" : "Quant result";
  }
  return language === "zh" ? "文档证据" : "Document";
}

function EvidenceMetadata({
  detail,
  language,
}: {
  detail: EvidenceDetail;
  language: "zh" | "en";
}) {
  const sourceHref = safeExternalHref(detail.source_url);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {detail.source_name ? <span>{detail.source_name}</span> : null}
      {detail.pit_timestamp ? (
        <span className="tabular">{new Date(detail.pit_timestamp).toLocaleString()}</span>
      ) : null}
      <span className="font-mono">{formatLocator(detail.locator)}</span>
      {sourceHref ? (
        <a
          className="inline-flex min-h-8 items-center gap-1.5 font-medium text-accent no-underline hover:underline"
          href={sourceHref}
          rel="noreferrer"
          target="_blank"
        >
          {language === "zh" ? "查看源站" : "Open source"}
          <ExternalLink className="size-3.5" />
        </a>
      ) : null}
    </div>
  );
}

function formatLocator(locator: EvidenceDetail["locator"]): string {
  if (typeof locator === "string") {
    return locator;
  }
  return Object.entries(locator)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
}

function HighlightedEvidence({
  detail,
  language,
}: {
  detail: EvidenceDetail;
  language: "zh" | "en";
}) {
  if (detail.highlights.length === 0) {
    return null;
  }
  return (
    <section className="rounded-2xl border border-caution/25 bg-caution-soft/55 p-5 md:p-6">
      <div className="flex items-center gap-2">
        <span className="grid size-8 place-items-center rounded-xl bg-caution text-white">
          <Highlighter className="size-4" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            {language === "zh" ? "本次引用" : "Cited passages"}
          </h2>
          <p className="text-xs text-muted-foreground">
            {language === "zh"
              ? "荧光标记是 Agent 实际用于回答或推荐的内容"
              : "Highlighted text was actually used in the answer or recommendation"}
          </p>
        </div>
      </div>
      <div className="mt-5 grid gap-3">
        {detail.highlights.map((highlight, index) => (
          <EvidenceExcerpt
            detail={detail}
            highlight={highlight}
            index={index}
            key={`${highlight.start}-${highlight.end}-${index}`}
          />
        ))}
      </div>
    </section>
  );
}

function EvidenceExcerpt({
  detail,
  highlight,
  index,
}: {
  detail: EvidenceDetail;
  highlight: EvidenceHighlight;
  index: number;
}) {
  const start = Math.max(0, Math.min(highlight.start, detail.markdown.length));
  const end = Math.max(start, Math.min(highlight.end, detail.markdown.length));
  const contextStart = Math.max(0, start - 90);
  const contextEnd = Math.min(detail.markdown.length, end + 90);
  const before = detail.markdown.slice(contextStart, start).replace(/\s+/g, " ");
  const marked = (detail.markdown.slice(start, end) || highlight.quote).replace(/\s+/g, " ");
  const after = detail.markdown.slice(end, contextEnd).replace(/\s+/g, " ");
  return (
    <blockquote className="rounded-xl border border-caution/20 bg-card/85 p-4 text-sm leading-7 text-foreground shadow-xs">
      {highlight.label ? (
        <span className="mb-2 block text-[11px] font-semibold tracking-wide text-caution uppercase">
          {highlight.label}
        </span>
      ) : null}
      <span aria-hidden="true">{contextStart > 0 ? "…" : ""}</span>
      {before}
      <mark className="rounded bg-highlight px-1 py-0.5 text-foreground box-decoration-clone">
        {marked}
      </mark>
      {after}
      <span aria-hidden="true">{contextEnd < detail.markdown.length ? "…" : ""}</span>
      <span className="sr-only">Evidence excerpt {index + 1}</span>
    </blockquote>
  );
}
