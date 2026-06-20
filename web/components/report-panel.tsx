/**
 * @fileoverview Panel component that displays a generated research report and
 * an optional downloadable export.
 */

import type { ReportExport, ResearchReport } from "@/lib/api";

/** Props for the ReportPanel component. */
type ReportPanelProps = {
  /** Research report data, or null when unavailable. */
  report: ResearchReport | null;
  /** Exported report file metadata, or null when not generated. */
  exported: ReportExport | null;
};

/**
 * Renders a research report preview with title, format, and export download.
 *
 * @param report Research report to display.
 * @param exported Export metadata for the report.
 * @returns The report panel or an empty state.
 */
export function ReportPanel({ report, exported }: ReportPanelProps) {
  if (!report) {
    return <div className="empty-state compact">报告暂不可用</div>;
  }

  const preview = report.content.split("\n").slice(0, 8).join("\n");

  return (
    <section className="panel report-panel" aria-labelledby="report-title">
      <div className="panel-heading">
        <h2 id="report-title">报告与导出</h2>
        <span>{report.format}</span>
      </div>
      <div className="report-meta">
        <strong>{report.title}</strong>
        <span>{exported?.filename ?? "暂未生成导出文件"}</span>
        <span>{exported?.mime_type ?? "--"}</span>
        {exported ? (
          <a
            className="secondary-link"
            download={exported.filename}
            href={`data:${exported.mime_type};charset=utf-8,${encodeURIComponent(
              exported.content,
            )}`}
          >
            下载导出文件
          </a>
        ) : null}
      </div>
      <pre>{preview}</pre>
    </section>
  );
}
