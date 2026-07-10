import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "@/lib/i18n";

import { EvidenceReader } from "./evidence-reader";

afterEach(cleanup);

describe("EvidenceReader", () => {
  it("renders the complete Markdown and the exact cited range", async () => {
    const markdown = [
      "# 2026 年一季报",
      "",
      "公司订单需求增长。",
      "",
      "报告期内产能利用率提升，出现供不应求。",
      "",
      "这是引用位置之后仍然保留的完整正文。",
    ].join("\n");
    const quote = "报告期内产能利用率提升，出现供不应求。";
    const start = markdown.indexOf(quote);
    const fetchDetail = vi.fn().mockResolvedValue({
      evidence_id: "ev-1",
      source_kind: "document",
      title: "2026 年一季报",
      source_level: "L1",
      source_url: "https://example.com/report.pdf",
      document_id: "doc-1",
      markdown,
      highlights: [{ start, end: start + quote.length, quote, label: "需求催化" }],
      locator: "paragraph:2",
      snapshot_id: "snap-1",
      pit_timestamp: "2026-04-30T08:00:00Z",
      source_name: "深交所",
    });

    render(
      <LanguageProvider>
        <EvidenceReader
          detailUrl="/api/v1/evidence/qres-1"
          evidenceId="ev-1"
          fetchDetail={fetchDetail}
          onOpenChange={() => undefined}
          open
        />
      </LanguageProvider>,
    );

    await waitFor(() =>
      expect(fetchDetail).toHaveBeenCalledWith(
        "ev-1",
        "/api/v1/evidence/qres-1",
      ),
    );
    expect(await screen.findByRole("heading", { name: "2026 年一季报", level: 1 }))
      .toBeInTheDocument();
    expect(screen.getByText("这是引用位置之后仍然保留的完整正文。")).toBeInTheDocument();
    expect(screen.getByText("本次引用")).toBeInTheDocument();
    expect(document.body.querySelector("mark")).toHaveTextContent(quote);
  });
});
