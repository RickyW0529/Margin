/**
 * @fileoverview Tests for the evidence locator list.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "@/lib/i18n";

import { EvidenceLocatorList } from "./evidence-locator-list";

afterEach(() => {
  cleanup();
});

describe("EvidenceLocatorList", () => {
  it("renders escaped titles without technical locator plumbing", () => {
    const { container } = render(
      <LanguageProvider>
        <EvidenceLocatorList
          evidence={[
            {
              evidence_id: "ev-1",
              title: "<img src=x onerror=alert(1)>",
              source_level: "L1",
              locator: "page 3",
              snapshot_id: "snap-1",
            },
          ]}
        />
      </LanguageProvider>,
    );

    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.getByText("L1")).toBeInTheDocument();
    expect(screen.queryByText("技术定位")).not.toBeInTheDocument();
    expect(screen.queryByText("page 3")).not.toBeInTheDocument();
    expect(screen.queryByText("snap-1")).not.toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows snippets and only flags unlinked evidence for review", () => {
    render(
      <LanguageProvider>
        <EvidenceLocatorList
          evidence={[
            {
              evidence_id: "evt-1",
              title: "投资者关系活动记录表",
              source_level: "L1",
              locator: "news_document",
              snapshot_id: "snap-1",
              snippet: "证券代码：002416 证券简称：爱施德",
              linked_to_security: true,
            },
            {
              evidence_id: "evt-2",
              title: "海目星年度报告",
              source_level: "L1",
              locator: "news_document",
              snapshot_id: "snap-2",
              snippet: "公司代码：688559 公司简称：海目星",
              linked_to_security: false,
            },
          ]}
        />
      </LanguageProvider>,
    );

    expect(screen.getByText("证券代码：002416 证券简称：爱施德")).toBeInTheDocument();
    expect(screen.getByText("已关联本股票")).toBeInTheDocument();
    expect(screen.getByText("需要人工复核关联股票")).toBeInTheDocument();
  });

  it("keeps direct WebSearch results on the source link instead of the evidence reader", () => {
    render(
      <LanguageProvider>
        <EvidenceLocatorList
          evidence={[
            {
              detail_url: "https://example.com/counter-evidence",
              evidence_id: "https://example.com/counter-evidence",
              locator: { source_type: "websearch" },
              source_kind: "websearch",
              source_level: "web",
              source_url: "https://example.com/counter-evidence",
              title: "公开信息反证",
            },
          ]}
        />
      </LanguageProvider>,
    );

    expect(screen.queryByRole("button", { name: "公开信息反证" })).toBeNull();
    expect(screen.getByRole("link", { name: /原文/ })).toHaveAttribute(
      "href",
      "https://example.com/counter-evidence",
    );
  });
});
