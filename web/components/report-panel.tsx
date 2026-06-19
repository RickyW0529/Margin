import type { ReportExport, ResearchReport } from "@/lib/api";

type ReportPanelProps = {
  report: ResearchReport | null;
  exported: ReportExport | null;
};

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
