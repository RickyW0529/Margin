"use client";

/**
 * @fileoverview Renderers for persisted Agent artifact payloads.
 */

import type { AgentArtifactDetail } from "@/lib/api";
import type { UiLanguage } from "@/lib/i18n";

type ArtifactRendererProps = {
  detail: AgentArtifactDetail;
  language: UiLanguage;
};

/** Renders a loaded artifact payload according to its artifact type. */
export function ArtifactDetailView({ detail, language }: ArtifactRendererProps) {
  if (detail.artifact_type === "analysis_table") {
    return <AnalysisTableArtifact detail={detail} language={language} />;
  }
  if (detail.artifact_type === "generated_file_ref") {
    return <GeneratedFileArtifact detail={detail} language={language} />;
  }
  if (detail.artifact_type === "chart_spec") {
    return <JsonArtifact detail={detail} language={language} title="Chart spec" />;
  }
  return <JsonArtifact detail={detail} language={language} title="Artifact JSON" />;
}

export function formatArtifactType(
  artifactType: string,
  language: UiLanguage,
): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    analysis_table: { en: "Analysis table", zh: "分析表" },
    chart_spec: { en: "Chart spec", zh: "图表说明" },
    computed_metric: { en: "Computed metric", zh: "计算指标" },
    explanation: { en: "Explanation", zh: "解释文本" },
    generated_file_ref: { en: "Generated file", zh: "生成文件" },
  };
  return labels[artifactType]?.[language] ?? artifactType;
}

function AnalysisTableArtifact({ detail, language }: ArtifactRendererProps) {
  const rows = getRecordRows(detail.payload_json.rows);
  const columns = getColumns(detail.payload_json.columns, rows);
  if (rows.length === 0 || columns.length === 0) {
    return <JsonArtifact detail={detail} language={language} title="Table JSON" />;
  }
  return (
    <div className="grid gap-3">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              {columns.map((column) => (
                <th key={column} className="px-2 py-2 font-medium">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 8).map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-border/70 last:border-0">
                {columns.map((column) => (
                  <td key={column} className="px-2 py-2 text-foreground">
                    {formatCellValue(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 8 ? (
        <p className="text-xs text-muted-foreground">
          {language === "zh"
            ? `仅显示前 8 行，共 ${rows.length} 行`
            : `Showing first 8 of ${rows.length} rows`}
        </p>
      ) : null}
      <ArtifactRefs detail={detail} language={language} />
    </div>
  );
}

function GeneratedFileArtifact({ detail, language }: ArtifactRendererProps) {
  const payload = detail.payload_json;
  const url = typeof payload.url === "string" ? payload.url : null;
  const mimeType = typeof payload.mime_type === "string" ? payload.mime_type : "";
  const title = typeof payload.title === "string" ? payload.title : detail.artifact_id;
  const isSafeRelativeUrl = Boolean(url?.startsWith("/"));
  return (
    <div className="grid gap-3">
      {isSafeRelativeUrl && mimeType.startsWith("image/") ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt={title}
          className="max-h-80 rounded-md border border-border object-contain"
          src={url ?? ""}
        />
      ) : null}
      <div className="grid gap-1 text-sm">
        <p className="font-medium">{title}</p>
        {mimeType ? <p className="text-muted-foreground">{mimeType}</p> : null}
        {isSafeRelativeUrl ? (
          <a
            className="text-accent underline-offset-4 hover:underline"
            href={url ?? undefined}
            rel="noreferrer"
            target="_blank"
          >
            {language === "zh" ? "打开文件" : "Open file"}
          </a>
        ) : (
          <p className="text-muted-foreground">
            {language === "zh"
              ? "文件引用已保存，当前未开放直接访问链接"
              : "File reference is saved; no direct link is exposed"}
          </p>
        )}
      </div>
      <ArtifactRefs detail={detail} language={language} />
    </div>
  );
}

function JsonArtifact({
  detail,
  language,
  title,
}: ArtifactRendererProps & { title: string }) {
  return (
    <div className="grid gap-3">
      <p className="text-sm font-medium">{title}</p>
      <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs leading-5 text-muted-foreground">
        {JSON.stringify(detail.payload_json, null, 2)}
      </pre>
      <ArtifactRefs detail={detail} language={language} />
    </div>
  );
}

function ArtifactRefs({ detail, language }: ArtifactRendererProps) {
  const refs = [...detail.source_refs, ...detail.evidence_refs];
  if (refs.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {refs.map((ref) => (
        <span
          key={ref}
          className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
        >
          {language === "zh" ? "来源" : "Source"}: {ref}
        </span>
      ))}
    </div>
  );
}

function getRecordRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function getColumns(value: unknown, rows: Record<string, unknown>[]): string[] {
  if (Array.isArray(value)) {
    const columns = value.filter((column): column is string => typeof column === "string");
    if (columns.length > 0) {
      return columns.slice(0, 8);
    }
  }
  return Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 8);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (typeof value === "string" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}
